"""Main CLI entry point for database schema generator."""

import random
import sys
from pathlib import Path

import click

from .config import load_config, GeneratorConfig
from .loaders.confidential_loader import ConfidentialDataLoader
from .generators.schema_generator import SchemaGenerator
from .generators.seed_generator import SeedDataGenerator
from .generators.query_generator import QueryGenerator
from .generators.ops_sequence_generator import (
    ServerNormalOpsGenerator,
    ServerFileHeavyOpsGenerator,
    DbLoadOpsGenerator,
)
# ParamGenerator is deprecated - params are now generated with seed data (single-pass)
# from .generators.param_generator import ParamGenerator
from .jmx import JMXGenerator


@click.group()
@click.option('--config', '-c', default='config.yaml', help='Path to config file')
@click.pass_context
def cli(ctx, config):
    """Database Schema Generator - Generate schemas, seed data, and queries for multiple databases."""
    ctx.ensure_object(dict)

    # Find config file
    config_path = Path(config)
    if not config_path.is_absolute():
        # Look in current directory and package directory
        if not config_path.exists():
            package_dir = Path(__file__).parent.parent
            config_path = package_dir / config
            if not config_path.exists():
                click.echo(f"Config file not found: {config}", err=True)
                sys.exit(1)

    ctx.obj['config'] = load_config(str(config_path))
    ctx.obj['config_dir'] = config_path.parent


@cli.command()
@click.option('--db', '-d', type=click.Choice(['postgresql', 'mssql', 'oracle', 'db2', 'all']),
              default='all', help='Database type to generate for')
@click.pass_context
def schema(ctx, db):
    """Generate database schema DDL files."""
    config: GeneratorConfig = ctx.obj['config']
    config_dir = ctx.obj['config_dir']

    generator = SchemaGenerator(config)

    if db == 'all':
        for db_config in config.databases:
            output_dir = config_dir / db_config.output_dir
            generator.generate_all(db_config.type, str(output_dir))
            click.echo(f"Generated schema for {db_config.type}")
    else:
        db_config = config.get_database_config(db)
        if db_config:
            output_dir = config_dir / db_config.output_dir
            generator.generate_all(db, str(output_dir))
            click.echo(f"Generated schema for {db}")
        else:
            click.echo(f"Database type {db} not configured", err=True)


@cli.command()
@click.option('--db', '-d', type=click.Choice(['postgresql', 'mssql', 'oracle', 'db2', 'all']),
              default='all', help='Database type to generate for')
@click.pass_context
def seed(ctx, db):
    """Generate seed data AND parameter CSV files (SINGLE-PASS).

    CRITICAL: This command generates both seed data and params together.
    Params contain ACTUAL values from the seed data, ensuring JMeter
    queries reference data that actually exists in the database.
    """
    config: GeneratorConfig = ctx.obj['config']
    config_dir = ctx.obj['config_dir']

    # Load confidential data
    conf_data_path = config.get_confidential_data_path(str(config_dir))
    click.echo(f"Loading confidential data from {conf_data_path}...")

    try:
        conf_loader = ConfidentialDataLoader(str(conf_data_path))
        conf_loader.load()
    except Exception as e:
        click.echo(f"Warning: Could not load confidential data: {e}", err=True)
        click.echo("Continuing with Faker data only...")
        conf_loader = None

    generator = SeedDataGenerator(config, conf_loader) if conf_loader else None

    if generator is None:
        click.echo("Seed generation requires confidential data loader", err=True)
        return

    click.echo("*** SINGLE-PASS GENERATION: Seed data + Params together ***")

    if db == 'all':
        for db_config in config.databases:
            output_dir = config_dir / db_config.output_dir
            generator.generate_all_seed_data(db_config.type, str(output_dir))
            click.echo(f"Generated seed data + params for {db_config.type}")
    else:
        db_config = config.get_database_config(db)
        if db_config:
            output_dir = config_dir / db_config.output_dir
            generator.generate_all_seed_data(db, str(output_dir))
            click.echo(f"Generated seed data + params for {db}")
        else:
            click.echo(f"Database type {db} not configured", err=True)


@cli.command()
@click.option('--db', '-d', type=click.Choice(['postgresql', 'mssql', 'oracle', 'db2', 'all']),
              default='all', help='Database type to generate for')
@click.pass_context
def queries(ctx, db):
    """Generate parameterized SQL queries."""
    config: GeneratorConfig = ctx.obj['config']
    config_dir = ctx.obj['config_dir']

    generator = QueryGenerator(config)

    if db == 'all':
        for db_config in config.databases:
            output_dir = config_dir / db_config.output_dir
            generator.generate_all(db_config.type, str(output_dir))
            click.echo(f"Generated queries for {db_config.type}")
    else:
        db_config = config.get_database_config(db)
        if db_config:
            output_dir = config_dir / db_config.output_dir
            generator.generate_all(db, str(output_dir))
            click.echo(f"Generated queries for {db}")
        else:
            click.echo(f"Database type {db} not configured", err=True)


@cli.command()
@click.option('--db', '-d', type=click.Choice(['postgresql', 'mssql', 'oracle', 'db2', 'all']),
              default='all', help='Database type to generate for')
@click.pass_context
def params(ctx, db):
    """Generate CSV parameter files for JMeter.

    NOTE: Params are now generated automatically with seed data (single-pass).
    This command is kept for backwards compatibility but simply runs 'seed'.

    Use 'seed' command instead for single-pass generation where params
    contain ACTUAL values from the seed data.
    """
    click.echo("=" * 60)
    click.echo("NOTE: Params are now generated with seed data (single-pass)")
    click.echo("Running 'seed' command to generate seed data + params...")
    click.echo("=" * 60)
    ctx.invoke(seed, db=db)


@cli.command(name='all')
@click.option('--db', '-d', type=click.Choice(['postgresql', 'mssql', 'oracle', 'db2', 'all']),
              default='all', help='Database type to generate for')
@click.pass_context
def generate_all(ctx, db):
    """Generate everything: schema, seed data + params, and queries.

    NOTE: Seed data and params are generated together in a SINGLE PASS.
    This ensures params contain ACTUAL values from the seed data.
    """
    click.echo("=" * 60)
    click.echo("Database Schema Generator - Full Generation")
    click.echo("=" * 60)

    click.echo("\n[1/3] Generating schemas...")
    ctx.invoke(schema, db=db)

    click.echo("\n[2/3] Generating seed data + params (SINGLE-PASS)...")
    ctx.invoke(seed, db=db)

    click.echo("\n[3/3] Generating queries...")
    ctx.invoke(queries, db=db)

    click.echo("\n" + "=" * 60)
    click.echo("Generation complete!")
    click.echo("  - Schemas: DDL for all tables")
    click.echo("  - Seed data: INSERT statements")
    click.echo("  - Params: CSV files with ACTUAL seed data values")
    click.echo("  - Queries: Parameterized SQL files")
    click.echo("=" * 60)


@cli.command()
@click.option('--template', '-t',
              type=click.Choice(['server-normal', 'server-file-heavy', 'server-file-confidential',
                                'db-load', 'all']),
              default='all', help='Template to generate')
@click.option('--db', '-d', type=click.Choice(['postgresql', 'mssql', 'oracle', 'db2', 'all']),
              default='all', help='Database type for db-load template')
@click.option('--output', '-o', default='output/jmx', help='Output directory for JMX files')
@click.pass_context
def jmx(ctx, template, db, output):
    """Generate JMeter test plan templates."""
    config_dir = ctx.obj['config_dir']
    output_dir = config_dir / output

    click.echo(f"Generating JMX templates to {output_dir}...")

    generator = JMXGenerator(str(output_dir))

    if template == 'all':
        # Generate all server templates
        click.echo("  Generating server-normal.jmx...")
        generator.generate_server_normal()

        click.echo("  Generating server-file-heavy.jmx...")
        generator.generate_server_file_heavy()

        click.echo("  Generating server-file-heavy_withconfidential.jmx...")
        generator.generate_server_file_confidential()

        # Generate db-load templates
        if db == 'all':
            for db_type in JMXGenerator.SUPPORTED_DB_TYPES:
                click.echo(f"  Generating db-load-{db_type}.jmx...")
                generator.generate_db_load(db_type)
        else:
            click.echo(f"  Generating db-load-{db}.jmx...")
            generator.generate_db_load(db)

    elif template == 'server-normal':
        click.echo("  Generating server-normal.jmx...")
        generator.generate_server_normal()

    elif template == 'server-file-heavy':
        click.echo("  Generating server-file-heavy.jmx...")
        generator.generate_server_file_heavy()

    elif template == 'server-file-confidential':
        click.echo("  Generating server-file-heavy_withconfidential.jmx...")
        generator.generate_server_file_confidential()

    elif template == 'db-load':
        if db == 'all':
            for db_type in JMXGenerator.SUPPORTED_DB_TYPES:
                click.echo(f"  Generating db-load-{db_type}.jmx...")
                generator.generate_db_load(db_type)
        else:
            click.echo(f"  Generating db-load-{db}.jmx...")
            generator.generate_db_load(db)

    click.echo("JMX generation complete!")


@cli.command(name='ops-sequence')
@click.option('--test-run-id', '-r', required=True, help='Test run ID (used for deterministic seed)')
@click.option('--template', '-t', required=True,
              type=click.Choice(['server-normal', 'server-file-heavy', 'db-load']),
              help='Template type')
@click.option('--loadprofile', '-l', required=True, help='Load profile name (e.g., low, medium, high)')
@click.option('--thread-count', type=int, required=True, help='Calibrated thread count')
@click.option('--duration', type=int, required=True, help='Test duration in seconds')
@click.option('--output', '-o', default='output/params', help='Output directory for CSV files')
@click.option('--conf-pct', type=float, default=10.0, help='Confidential file percentage (file-heavy only)')
@click.option('--zip-pct', type=float, default=20.0, help='Zip output percentage (file-heavy only)')
@click.option('--db', '-d', type=click.Choice(['postgresql', 'mssql', 'oracle', 'db2']),
              default='postgresql', help='Database type (db-load only)')
@click.pass_context
def ops_sequence(ctx, test_run_id, template, loadprofile, thread_count,
                 duration, output, conf_pct, zip_pct, db):
    """Generate deterministic operation sequence CSV for a load profile.

    The CSV is consumed by JMeter via CSV Data Set Config + If Controllers.
    Same (test-run-id, loadprofile) always produces the same sequence.

    Called by the orchestrator after calibration determines thread counts.
    Can also be run manually for debugging or pre-generation.
    """
    config_dir = ctx.obj.get('config_dir', Path('.'))
    output_dir = Path(config_dir) / output
    output_dir.mkdir(parents=True, exist_ok=True)

    count = ServerNormalOpsGenerator.calculate_sequence_length(
        thread_count, duration
    )

    if template == 'server-normal':
        gen = ServerNormalOpsGenerator(test_run_id, loadprofile)
        ops = gen.generate(count)
        csv_name = f"ops_sequence_{loadprofile}.csv"
        out_path = str(output_dir / csv_name)
        gen.write_csv(ops, out_path)

    elif template == 'server-file-heavy':
        # For CLI usage, provide placeholder file IDs.
        # In production, the orchestrator supplies actual file IDs from
        # the emulator's configured input_folders.
        normal_files = [f"rfc{i}" for i in range(791, 810)]
        confidential_files = [f"conf{i:03d}" for i in range(1, 6)]
        gen = ServerFileHeavyOpsGenerator(
            test_run_id, loadprofile,
            normal_files=normal_files,
            confidential_files=confidential_files,
        )
        ops = gen.generate(count, confidential_percent=conf_pct, zip_percent=zip_pct)
        csv_name = f"ops_sequence_{loadprofile}.csv"
        out_path = str(output_dir / csv_name)
        gen.write_csv(ops, out_path)

    elif template == 'db-load':
        # For CLI usage, provide placeholder parameter pools.
        # In production, the orchestrator loads these from seed data CSVs.
        customer_ids = list(range(1, 5001))
        order_params = [
            {'order_id': i, 'status': s, 'amount': round(random.uniform(10, 5000), 2)}
            for i, s in zip(
                range(1, 501),
                ['PENDING', 'SHIPPED', 'DELIVERED', 'CANCELLED'] * 125,
            )
        ]
        product_ids = list(range(1, 2001))
        patient_ids = list(range(1, 5001))
        account_ids = list(range(1, 5001))

        from .utils.db_type_mapper import get_cached_ddl_types
        column_types = get_cached_ddl_types(db)
        ddl_tables = [f"ddl_test_{i:03d}" for i in range(1, 21)]
        ddl_params = [
            {'table_name': t, 'column_name': f"test_field_{i:03d}", 'column_type': ct}
            for i, (t, ct) in enumerate(
                zip(ddl_tables * 5, column_types * 17), start=1
            )
        ][:100]

        grant_params = [
            {'table_name': t, 'username': u}
            for t in ['orders', 'customers', 'products', 'accounts',
                       'patients', 'credit_cards', 'medical_records']
            for u in ['test_user_1', 'test_user_2', 'test_admin']
        ]
        temp_users = [
            {'username': f"load_user_{i:03d}", 'password': f"LoadTest@{i:03d}"}
            for i in range(1, 51)
        ]
        config_users = ['test_user_1', 'test_user_2', 'test_admin']

        gen = DbLoadOpsGenerator(
            test_run_id, loadprofile,
            customer_ids=customer_ids,
            order_params=order_params,
            product_ids=product_ids,
            patient_ids=patient_ids,
            account_ids=account_ids,
            ddl_params=ddl_params,
            grant_params=grant_params,
            temp_users=temp_users,
            config_users=config_users,
            db_type=db,
        )
        ops = gen.generate(count)
        csv_name = f"db_ops_sequence_{loadprofile}.csv"
        out_path = str(output_dir / csv_name)
        gen.write_csv(ops, out_path)

    click.echo(f"Generated {count} operations -> {out_path}")


@cli.command()
@click.pass_context
def info(ctx):
    """Display configuration information."""
    config: GeneratorConfig = ctx.obj['config']

    click.echo("Database Schema Generator Configuration")
    click.echo("=" * 40)
    click.echo(f"\nTable Counts:")
    click.echo(f"  E-Commerce: {config.schema.table_counts.ecommerce}")
    click.echo(f"  Banking:    {config.schema.table_counts.banking}")
    click.echo(f"  Healthcare: {config.schema.table_counts.healthcare}")
    click.echo(f"  Shared:     {config.schema.table_counts.shared}")
    click.echo(f"  Total:      {config.schema.table_counts.total}")

    click.echo(f"\nSeed Data:")
    click.echo(f"  Records per table: {config.seed_data.records_per_table}")
    click.echo(f"  Batch size:        {config.seed_data.batch_size}")
    click.echo(f"  Data source:       {config.seed_data.confidential_data_source}")

    click.echo(f"\nQuery Generation:")
    click.echo(f"  Param rows: {config.query_generation.param_rows_per_query}")

    click.echo(f"\nConfigured Databases:")
    for db_config in config.databases:
        click.echo(f"  - {db_config.type}: {db_config.output_dir}")

    click.echo(f"\nTest Users:")
    for user in config.test_users:
        click.echo(f"  - {user.username} ({user.role})")


def main():
    """Main entry point."""
    cli(obj={})


if __name__ == '__main__':
    main()
