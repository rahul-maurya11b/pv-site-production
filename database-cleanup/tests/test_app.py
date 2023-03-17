import datetime as dt
import uuid

import pytest
import sqlalchemy as sa
from click.testing import CliRunner
from database_cleanup.app import main
from pvsite_datamodel.sqlmodels import ClientSQL, ForecastSQL, ForecastValueSQL, SiteSQL
from sqlalchemy.orm import Session


def _add_foreasts(
    session: Session,
    *,
    site_uuid: str,
    timestamps: list[dt.datetime],
    num_values: int,
    frequency: int
):
    for timestamp in timestamps:
        forecast = ForecastSQL(site_uuid=site_uuid, timestamp_utc=timestamp, forecast_version="0")
        session.add(forecast)
        session.commit()

        for i in range(num_values):
            # N forecasts every minute.
            fv = ForecastValueSQL(
                forecast_uuid=forecast.forecast_uuid,
                forecast_power_kw=i,
                horizon_minutes=i,
                start_utc=timestamp + dt.timedelta(minutes=i * frequency),
                end_utc=timestamp + dt.timedelta(minutes=(i + 1) * frequency),
            )
            session.add(fv)
        session.commit()


def _run_cli(func, args: list[str]):
    runner = CliRunner()
    result = runner.invoke(func, args, catch_exceptions=True)

    # Without this the output to stdout/stderr is grabbed by click's test runner.
    if result.output:
        print(result.output)

    # In case of an exception, raise it so that the test fails with the exception.
    if result.exception:
        raise result.exception

    assert result.exit_code == 0


@pytest.fixture
def site(session):
    # Create a new site (this way we know it won't have any forecasts yet).
    client = ClientSQL(client_name=str(uuid.uuid4()))
    session.add(client)
    session.commit()

    site = SiteSQL(client_uuid=client.client_uuid, ml_id=hash(uuid.uuid4()) % 2147483647)
    session.add(site)
    session.commit()
    return site


@pytest.mark.parametrize("batch_size", [None, 10, 1000])
@pytest.mark.parametrize(
    "date_str,expected",
    [
        ["2019-12-31 23:59", 10],
        ["2020-01-01 00:00", 10],
        ["2020-01-02 00:00", 9],
        ["2020-01-09 00:00", 2],
        ["2020-01-10 00:00", 1],
        ["2020-01-30 00:00", 0],
    ],
)
def test_app(session: Session, site, batch_size: int, date_str: str, expected: int):
    # We'll only consider this site.
    site_uuid = site.site_uuid

    # Write some forecasts to the database for our site.
    num_forecasts = 10
    num_values = 9

    timestamps = [dt.datetime(2020, 1, d + 1) for d in range(num_forecasts)]

    # Add forecasts for those.
    _add_foreasts(
        session,
        site_uuid=site_uuid,
        timestamps=timestamps,
        num_values=num_values,
        frequency=1,
    )

    # Run the script.
    args = ["--date", date_str, "--do-delete"]

    if batch_size is not None:
        args.extend(["--batch-size", str(batch_size)])

    _run_cli(main, args)

    # Check that we have the right number of rows left.
    # Only check for the site_uuid that we considered.
    num_forecasts_left = session.scalars(
        sa.select(sa.func.count())
        .select_from(ForecastSQL)
        .where(ForecastSQL.site_uuid == site_uuid)
    ).one()
    assert num_forecasts_left == expected

    num_values_left = session.scalars(
        sa.select(sa.func.count())
        .select_from(ForecastValueSQL)
        .join(ForecastSQL)
        .where(ForecastSQL.site_uuid == site_uuid)
    ).one()
    assert num_values_left == expected * num_values