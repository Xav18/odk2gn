import logging
import click
import uuid
import csv
import json

import flatdict
from sqlalchemy.orm import exc
from sqlalchemy.exc import SQLAlchemyError


from pyodk.client import Client
from datetime import datetime
from geonature.utils.env import DB
from pypnnomenclature.models import (
    TNomenclatures, BibNomenclaturesTypes, CorTaxrefNomenclature
)
from geonature.core.users.models import (
    VUserslistForallMenu
)

from apptax.taxonomie.models import BibListes, CorNomListe, Taxref, BibNoms

from geonature.app import create_app
from geonature.utils.env import BACKEND_DIR
from geonature.core.gn_commons.models import BibTablesLocation

client = Client('../.pyodk_config.toml')
log = logging.getLogger("app")


def get_taxons(id_liste):
#returns the list of taxons
    data = (
        DB.session.query(Taxref.cd_nom, Taxref.nom_complet, Taxref.nom_vern)
        .filter(BibNoms.cd_nom == Taxref.cd_nom)
        .filter(BibNoms.id_nom == CorNomListe.id_nom)
        .filter(CorNomListe.id_liste == id_liste)
        .all()
    )
    header = 'cd_nom,nom_complet,nom_vern'
    return {'header': header, 'data': data}


def get_observers(id_liste):
#returns the list of observers
    data = DB.session.query(VUserslistForallMenu.id_role, VUserslistForallMenu.nom_complet).filter_by(id_menu=id_liste)
    header='id_role,nom_complet'
    return {'header' : header, 'data': data}

def get_organizations():
#returns the list of organizations
    data = 'placeholder'
    header = ''
    return {'header' : header, 'data': data}


def get_nomenclatures():
#returns the list of nomenclatures
    nomenclatures = ['TYPE_PERTURBATION', 'INCLINE_TYPE', 'PHYSIOGNOMY_TYPE', 'HABITAT_STATUS', 'THREAT_LEVEL', 'PHENOLOGY_TYPE', 'FREQUENCY_METHOD', 'COUNTING_TYPE']
    data = DB.session.query(
        BibNomenclaturesTypes.mnemonique,
        TNomenclatures.id_nomenclature,
        TNomenclatures.cd_nomenclature,
        TNomenclatures.label_default
    ).filter(
        BibNomenclaturesTypes.id_type == TNomenclatures.id_type
    ).filter(
        BibNomenclaturesTypes.mnemonique.in_(nomenclatures)
    )
    header='mnemonique,id_nomenclature,cd_nomenclature,label_default'
    return {'header': header, 'data': data}



def to_csv(file_name, header, data):
#creates a csv file containing the requested elements from the db
    with open(file_name, mode='w') as file:
        writer = csv.writer(file, delimiter=',')

        writer.writerow(header)
        for d in data:
            writer.writerow(d)

    return {'file_name' : file_name, 'content' : file}

def draft(project_id, form_id):
#sets the ODK central entry for the form to a draft state
    with client:
        request = client.post(f"projects/{project_id}/forms/{form_id}/draft")
        assert request.status_code == 200


def write_files():
#updates the csv file attachments on ODK central
    files = []
    nomenclatures = get_nomenclatures()
    files.append(
        to_csv('pf_nomenclatures.csv', nomenclatures['header'], nomenclatures['data'])
    )
    taxons = get_taxons()
    files.append(
        to_csv('pf_taxons.csv', taxons['header'], taxons['data'])
    )
    observers = get_observers()
    files.append(
        to_csv('pf_observers.csv', observers['header'], observers['data'])
    )
    organizations = get_organizations()
    files.append(
        to_csv('pf_organizations.csv', organizations['header'], organizations['data'])
    )
    return files 


def upload_file(project_id, form_id, file_name, data):
    response = client.post(
        f"{client.config.central.base_url}/v1/projects/{project_id}/forms/{form_id}/draft/attachments/{file_name}",
        data=data.encode("utf-8", "strict"),
    )
    if response.status_code == 404:
        log.warning(
            f"Le fichier {file_name} n'existe pas dans la définition du formulaire"
        )
    elif response.status_code == 200:
        log.info(f"fichier {file_name} téléversé")
    else:
        # TODO raise error
        pass


def publish(project_id, form_id):
#publishes the form
    version_number = datetime.now()
    response = client.post(
        f"projects/{project_id}/forms/{form_id}/draft/publish?version={version_number}"
    )
    assert response.status_code == 200

def update_review_state(project_id, form_id, submission_id, review_state):
#updates the review state of the submissions
    token = client.session.auth.service.get_token(
        username=client.config.central.username,
        password=client.config.central.password,
    )
    review_submission_response = client.patch(
        f"{client.config.central.base_url}/v1/projects/{project_id}/forms/{form_id}/submissions/{submission_id}",
        data=json.dumps({"reviewState": review_state}),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        },
    )
    try:
        assert review_submission_response.status_code == 200
    except AssertionError:
        log.error("Error while update submision state")

def update_odk_form(project_id, form_id):
#updates the odk form with the new csv files
    files = write_files()
    draft(project_id, form_id)
    for file in files:
        upload_file(project_id, form_id, file['file_name'], file['content'])
    publish(project_id, form_id)


def get_submissions(project_id, form_id):
    # Creation client odk central
    form_data = None
    with client:
        form_data = client.submissions.get_table(
            form_id=form_id,
            project_id=project_id,
            expand="*",
            # TODO : try received or edited (but edited not actually support)
            filter="__system/reviewState ne 'approved' and __system/reviewState ne 'hasIssues' and __system/reviewState ne 'rejected'",
            # filter="__system/reviewState eq 'rejected'",
        )
        return form_data["value"]


def format_geoshape():
#formats the geoshape for the db
    pass

def update_priority_flora_db(project_id, form_id):
#adds the new ODK submissions to the db
    form_data = get_submissions(project_id, form_id)
    for sub in form_data:
        flat_data = flatdict.FlatDict(sub, delimiter="/")