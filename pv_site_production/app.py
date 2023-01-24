"""
Apply the model to the PVs in the database and note the results.
"""

import logging
import os
import pathlib
from datetime import datetime

import click
import dotenv
from nowcasting_datamodel.connection import DatabaseConnection
from nowcasting_datamodel.models.base import Base_PV
from psp.ml.models.base import PvSiteModel

from pv_site_production.data.pv_data_sources import DbPvDataSource
from pv_site_production.models.common import apply_model
from pv_site_production.utils.config import load_config
from pv_site_production.utils.imports import import_from_module

_log = logging.getLogger(__name__)


@click.command()
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(path_type=pathlib.Path),
    help="Config defining the model to use and its parameters.",
)
@click.option(
    "--date",
    "-d",
    "timestamp",
    type=click.DateTime(formats=["%Y-%m-%d-%H-%M"]),
    default=None,
    help='Date-time (UTC) at which to make the prediction. Defaults to "now".',
)
@click.option(
    "--max-pvs",
    type=int,
    default=None,
    help="Maximum number of PVs to treat. This is useful for testing.",
)
def main(
    config_path: pathlib.Path,
    timestamp: datetime | None,
    max_pvs: int | None,
):
    """Main function"""

    _log.debug("Load the configuration file")
    # Typically the configuration will contain many placeholders pointing to environment variables.
    # We allow specifying them in a .env file. See the .env.dist for a list of expected variables.
    # Environment variables still have precedence.
    dotenv_variables = dotenv.dotenv_values()
    config = load_config(config_path, dotenv_variables | os.environ)

    if timestamp is None:
        timestamp = datetime.utcnow()

    get_model = import_from_module(config["run_model_func"])

    _log.debug("Connecting to pv database")
    url = config["pv_db_url"]
    pv_db_connection = DatabaseConnection(url=url, base=Base_PV, echo=False)

    # Wrap into a PV data source for the models.
    _log.debug("Creating PV data source")
    pv_data_source = DbPvDataSource(pv_db_connection, config["pv_metadata_path"])

    _log.debug("Loading model")
    model: PvSiteModel = get_model(config, pv_data_source)

    pv_ids = pv_data_source.list_pv_ids()

    if max_pvs is not None:
        pv_ids = pv_ids[:max_pvs]

    _log.info("Applying model")
    results_df = apply_model(model, pv_ids=pv_ids, ts=timestamp)

    # _log.info('Saving results to database')
    # TODO Save the results to the database. In the meantime we print them.
    for _, row in results_df.iterrows():
        print(f"{row['pv_uuid']} | {row['target_datetime_utc']} | {row['forecast_kw']}")


if __name__ == "__main__":
    main()
