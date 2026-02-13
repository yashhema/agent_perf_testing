"""JDBC Sampler Element Builders.

Creates JDBC elements for database operations.
"""

import xml.etree.ElementTree as ET
from typing import List, Optional
from .base import create_string_prop, create_bool_prop, create_element_prop


def create_jdbc_connection_config(
    name: str,
    variable_name: str,
    db_url: str = "${DB_URL}",
    driver_class: str = "${DB_DRIVER}",
    username: str = "${DB_USER}",
    password: str = "${DB_PASSWORD}",
    pool_max: int = 10,
    timeout_ms: int = 10000,
    auto_commit: bool = True
) -> ET.Element:
    """Create a JDBC Connection Configuration element.

    Args:
        name: Configuration name
        variable_name: Variable name to reference this pool (e.g., 'db_pool')
        db_url: JDBC connection URL
        driver_class: JDBC driver class name
        username: Database username
        password: Database password
        pool_max: Maximum number of connections in pool
        timeout_ms: Connection timeout in milliseconds
        auto_commit: Whether to auto-commit transactions
    """
    config = ET.Element('JDBCDataSource', {
        'guiclass': 'TestBeanGUI',
        'testclass': 'JDBCDataSource',
        'testname': name,
        'enabled': 'true'
    })

    config.append(create_string_prop('dataSource', variable_name))
    config.append(create_string_prop('dbUrl', db_url))
    config.append(create_string_prop('driver', driver_class))
    config.append(create_string_prop('username', username))
    config.append(create_string_prop('password', password))

    config.append(create_bool_prop('autocommit', auto_commit))
    config.append(create_string_prop('poolMax', str(pool_max)))
    config.append(create_string_prop('timeout', str(timeout_ms)))
    config.append(create_string_prop('trimInterval', '60000'))
    config.append(create_string_prop('connectionAge', '5000'))
    config.append(create_string_prop('checkQuery', ''))
    config.append(create_string_prop('connectionProperties', ''))
    config.append(create_string_prop('initQuery', ''))
    config.append(create_bool_prop('keepAlive', True))
    config.append(create_string_prop('transactionIsolation', 'DEFAULT'))
    config.append(create_bool_prop('preinit', False))

    return config


def create_jdbc_sampler(
    name: str,
    pool_name: str,
    query: str,
    query_type: str = "Prepared Select Statement",
    parameters: str = "",
    parameter_types: str = "",
    variable_names: str = "",
    result_variable: str = ""
) -> ET.Element:
    """Create a JDBC Request Sampler element.

    Args:
        name: Sampler name
        pool_name: JDBC connection pool variable name (from JDBCDataSource)
        query: SQL query to execute
        query_type: Type of query:
            - "Select Statement" - Simple SELECT
            - "Prepared Select Statement" - Parameterized SELECT
            - "Update Statement" - INSERT/UPDATE/DELETE/DDL
            - "Prepared Update Statement" - Parameterized INSERT/UPDATE/DELETE
            - "Callable Statement" - Stored procedure
        parameters: Comma-separated parameter values (e.g., "${customer_id},${status}")
        parameter_types: Comma-separated JDBC types (e.g., "INTEGER,VARCHAR")
        variable_names: Comma-separated variable names for result columns
        result_variable: Variable name to store entire result set
    """
    sampler = ET.Element('JDBCSampler', {
        'guiclass': 'TestBeanGUI',
        'testclass': 'JDBCSampler',
        'testname': name,
        'enabled': 'true'
    })

    sampler.append(create_string_prop('dataSource', pool_name))
    sampler.append(create_string_prop('query', query))
    sampler.append(create_string_prop('queryType', query_type))
    sampler.append(create_string_prop('queryArguments', parameters))
    sampler.append(create_string_prop('queryArgumentsTypes', parameter_types))
    sampler.append(create_string_prop('variableNames', variable_names))
    sampler.append(create_string_prop('resultVariable', result_variable))
    sampler.append(create_string_prop('queryTimeout', ''))
    sampler.append(create_string_prop('resultSetMaxRows', ''))
    sampler.append(create_string_prop('resultSetHandler', 'Store as String'))

    return sampler


def create_csv_data_set_config(
    name: str,
    filename: str,
    variable_names: str,
    delimiter: str = ",",
    recycle: bool = True,
    stop_thread: bool = False,
    share_mode: str = "shareMode.all",
    ignore_first_line: bool = True
) -> ET.Element:
    """Create a CSV Data Set Config element.

    Args:
        name: Config element name
        filename: Path to CSV file (can use JMeter variables)
        variable_names: Comma-separated variable names for each column
        delimiter: Field delimiter
        recycle: Whether to recycle at end of file
        stop_thread: Whether to stop thread at end of file
        share_mode: How to share data between threads:
            - "shareMode.all" - All threads share same file pointer
            - "shareMode.group" - Each thread group has own pointer
            - "shareMode.thread" - Each thread has own pointer
        ignore_first_line: Whether to skip header row
    """
    config = ET.Element('CSVDataSet', {
        'guiclass': 'TestBeanGUI',
        'testclass': 'CSVDataSet',
        'testname': name,
        'enabled': 'true'
    })

    config.append(create_string_prop('filename', filename))
    config.append(create_string_prop('fileEncoding', 'UTF-8'))
    config.append(create_string_prop('variableNames', variable_names))
    config.append(create_string_prop('delimiter', delimiter))
    config.append(create_bool_prop('quotedData', False))
    config.append(create_bool_prop('recycle', recycle))
    config.append(create_bool_prop('stopThread', stop_thread))
    config.append(create_string_prop('shareMode', share_mode))
    config.append(create_bool_prop('ignoreFirstLine', ignore_first_line))

    return config


# Pre-defined JDBC samplers for common operations

def create_select_sampler(
    name: str,
    pool_name: str,
    table: str,
    columns: str = "*",
    where_clause: str = "",
    parameters: str = "",
    parameter_types: str = ""
) -> ET.Element:
    """Create a SELECT query sampler."""
    query = f"SELECT {columns} FROM {table}"
    if where_clause:
        query += f" WHERE {where_clause}"

    query_type = "Prepared Select Statement" if parameters else "Select Statement"

    return create_jdbc_sampler(
        name=name,
        pool_name=pool_name,
        query=query,
        query_type=query_type,
        parameters=parameters,
        parameter_types=parameter_types
    )


def create_insert_sampler(
    name: str,
    pool_name: str,
    table: str,
    columns: List[str],
    parameters: str,
    parameter_types: str
) -> ET.Element:
    """Create an INSERT query sampler."""
    col_list = ", ".join(columns)
    placeholders = ", ".join(["?" for _ in columns])
    query = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"

    return create_jdbc_sampler(
        name=name,
        pool_name=pool_name,
        query=query,
        query_type="Prepared Update Statement",
        parameters=parameters,
        parameter_types=parameter_types
    )


def create_update_sampler(
    name: str,
    pool_name: str,
    table: str,
    set_clause: str,
    where_clause: str,
    parameters: str,
    parameter_types: str
) -> ET.Element:
    """Create an UPDATE query sampler."""
    query = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"

    return create_jdbc_sampler(
        name=name,
        pool_name=pool_name,
        query=query,
        query_type="Prepared Update Statement",
        parameters=parameters,
        parameter_types=parameter_types
    )


def create_delete_sampler(
    name: str,
    pool_name: str,
    table: str,
    where_clause: str,
    parameters: str,
    parameter_types: str
) -> ET.Element:
    """Create a DELETE query sampler."""
    query = f"DELETE FROM {table} WHERE {where_clause}"

    return create_jdbc_sampler(
        name=name,
        pool_name=pool_name,
        query=query,
        query_type="Prepared Update Statement",
        parameters=parameters,
        parameter_types=parameter_types
    )


def create_ddl_sampler(
    name: str,
    pool_name: str,
    query: str
) -> ET.Element:
    """Create a DDL (ALTER TABLE, CREATE, etc.) query sampler."""
    return create_jdbc_sampler(
        name=name,
        pool_name=pool_name,
        query=query,
        query_type="Update Statement"
    )
