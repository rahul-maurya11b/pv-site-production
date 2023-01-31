"""
Apply the model to the PVs in the database and note the results.
"""

import logging
import os
import pathlib
from datetime import datetime

import click
import dotenv
from psp.ml.models.base import PvSiteModel
from pvsite_datamodel.connection import DatabaseConnection
from pvsite_datamodel.write import insert_forecast_values

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
@click.option(
    "--write-to-db",
    is_flag=True,
    default=False,
    help="Set this flag to actually write the results to the database."
    "By default we only print to stdout",
)
def main(
    config_path: pathlib.Path,
    timestamp: datetime | None,
    max_pvs: int | None,
    write_to_db: bool,
):
    """Main function"""

    _log.debug("Load the configuration file")
    # Typically the configuration will contain many placeholders pointing to environment variables.
    # We allow specifying them in a .env file. See the .env.dist for a list of expected variables.
    # Environment variables still have precedence.

    # We remove the `None` values because that's how we typed `load_config`.
    dotenv_variables = {k: v for k, v in dotenv.dotenv_values().items() if v is not None}
    config = load_config(config_path, dotenv_variables | os.environ)

    if timestamp is None:
        timestamp = datetime.utcnow()

    get_model = import_from_module(config["run_model_func"])

    _log.debug("Connecting to pv database")
    url = config["pv_db_url"]

    database_connection = DatabaseConnection(url)

    # Wrap into a PV data source for the models.
    _log.debug("Creating PV data source")
    pv_data_source = DbPvDataSource(database_connection, config["pv_metadata_path"])

    _log.debug("Loading model")
    model: PvSiteModel = get_model(config, pv_data_source)

    pv_ids = pv_data_source.list_pv_ids()
    _log.debug(f"Treating {len(pv_ids)} sites")

    if max_pvs is not None:
        pv_ids = pv_ids[:max_pvs]

    _log.info("Applying model")
    results_df = apply_model(model, pv_ids=pv_ids, ts=timestamp)

    if write_to_db:
        _log.info("Writing forecasts to DB")

        # TODO Make `insert_forecast_values` support (expect?) datetimes.
        # Currently `insert_forecast_values` expects datetimes as string with ISO formatting.
        results_df["target_datetime_utc"] = results_df["target_datetime_utc"].dt.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        with database_connection.get_session() as session:  # type: ignore
            insert_forecast_values(session, results_df)
    else:
        # When we don't write to the DB, we print to stdout instead.
        for _, row in results_df.iterrows():
            print(f"{row['pv_uuid']} | {row['target_datetime_utc']} | {row['forecast_kw']}")


if __name__ == "__main__":
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOGLEVEL", "WARNING").upper()),
        format="[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s",
    )
    main()
