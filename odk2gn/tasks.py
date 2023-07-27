import os
import time
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func
from celery.utils.log import get_task_logger
from celery.schedules import crontab
from flask import current_app
from geonature.utils.celery import celery_app
from odk2gn.commands import synchronize_module, upgrade_module
from odk2gn.config import CentralSchema
from odk2gn.gn2_utils import get_module_code
from odk2gn.models import TOdkForm


if sys.version_info < (3, 10):
    from importlib_metadata import entry_points
else:
    from importlib.metadata import entry_points

logger = get_task_logger(__name__)


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        crontab(minute=0, hour="*/1"),
        synchronize_all_modules.s(),
        name="synchronize_monitoring_modules",
    )
    sender.add_periodic_task(
        crontab(minute=0, hour=12),
        upgrade_all_forms.s(),
        name="upgrade_monitoring_modules",
    )


from click import Context
from odk2gn.commands import synchronize_monitoring, synchronize, upgrade_odk_form


@celery_app.task(bind=True)
def synchronize_all_modules(self):
    for form in TOdkForm.query.all():
        logger.info(f"----Synchronizing module {form.module.module_code}----")
        for key, cmd in synchronize.commands.items():
            if form.upgrade_command_name == cmd.name:
                if form.module.type == "monitoring_module":
                    cmd.callback(
                        module_code=form.module.module_code,
                        project_id=form.odk_project_id,
                        form_id=form.odk_form_id,
                    )
                else:
                    cmd.callback(project_id=form.odk_project_id, form_id=form.odk_form_id)
        logger.info(f"----{form.module.module_code} module synchronized at----")
        time.sleep(2)


@celery_app.task(bind=True)
def upgrade_all_forms(self):
    for form in TOdkForm.query.all():
        logger.info(f"----Upgrading form for module {form.module.module_code}----")
        for key, cmd in upgrade_odk_form.commands.items():
            if form.upgrade_command_name == cmd.name:
                if form.module.type == "monitoring_module":
                    cmd.callback(
                        module_code=form.module.module_code,
                        project_id=form.odk_project_id,
                        form_id=form.odk_form_id,
                        skip_taxons=False,
                        skip_sites=False,
                        skip_jdd=False,
                        skip_sites_groups=False,
                        skip_nomenclatures=False,
                        skip_observers=False,
                    )
                else:
                    cmd.callback(project_id=form.odk_project_id, form_id=form.odk_form_id)
        logger.info(f"---{form.module.module_code} module upgraded----")
        time.sleep(2)
