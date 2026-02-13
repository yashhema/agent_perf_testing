"""JMX Controller Element Builders.

Creates controller elements like ThroughputController, IfController,
CSVDataSet, etc.
"""

import xml.etree.ElementTree as ET
from .base import create_string_prop, create_bool_prop, create_int_prop


def create_csv_data_set_config(
    name: str = "Operation Sequence CSV",
    filename: str = "${OPS_SEQUENCE}",
    variable_names: str = "seq_id,op_type",
    delimiter: str = ",",
    ignore_first_line: bool = True,
    allow_quoted_data: bool = True,
    recycle_on_eof: bool = True,
    stop_thread_on_eof: bool = False,
    sharing_mode: str = "shareMode.all"
) -> ET.Element:
    """Create a CSV Data Set Config element.

    Args:
        name: Config element name
        filename: Path to CSV file (can use JMeter variable like ${OPS_SEQUENCE})
        variable_names: Comma-separated variable names matching CSV columns
        delimiter: Column delimiter
        ignore_first_line: Skip header row
        allow_quoted_data: Allow quoted values in CSV
        recycle_on_eof: Restart from beginning when CSV ends
        stop_thread_on_eof: Stop thread when CSV ends (usually False with recycle)
        sharing_mode: How CSV is shared across threads
            - "shareMode.all" = All threads share same iterator
            - "shareMode.group" = Each thread group gets own iterator
            - "shareMode.thread" = Each thread gets own iterator
    """
    config = ET.Element('CSVDataSet', {
        'guiclass': 'TestBeanGUI',
        'testclass': 'CSVDataSet',
        'testname': name,
        'enabled': 'true'
    })

    config.append(create_string_prop('delimiter', delimiter))
    config.append(create_string_prop('fileEncoding', 'UTF-8'))
    config.append(create_string_prop('filename', filename))
    config.append(create_bool_prop('ignoreFirstLine', ignore_first_line))
    config.append(create_bool_prop('quotedData', allow_quoted_data))
    config.append(create_bool_prop('recycle', recycle_on_eof))
    config.append(create_string_prop('shareMode', sharing_mode))
    config.append(create_bool_prop('stopThread', stop_thread_on_eof))
    config.append(create_string_prop('variableNames', variable_names))

    return config


def create_float_prop(name: str, value: float) -> ET.Element:
    """Create a stringProp element for float values.

    Note: JMeter 5.x uses stringProp for ThroughputController percentage,
    not floatProp which is deprecated.
    """
    elem = ET.Element('stringProp', {'name': name})
    elem.text = str(value)
    return elem


def create_throughput_controller(
    name: str,
    percent: float,
    per_thread: bool = True
) -> ET.Element:
    """Create a Throughput Controller element.

    Args:
        name: Controller name
        percent: Percentage of requests to execute (0-100)
        per_thread: If True, percentage is per thread; if False, total
    """
    controller = ET.Element('ThroughputController', {
        'guiclass': 'ThroughputControllerGui',
        'testclass': 'ThroughputController',
        'testname': name,
        'enabled': 'true'
    })

    # Style: 1 = percent executions
    controller.append(create_int_prop('ThroughputController.style', 1))
    controller.append(create_bool_prop('ThroughputController.perThread', per_thread))
    controller.append(create_int_prop('ThroughputController.maxThroughput', 1))
    controller.append(create_float_prop('ThroughputController.percentThroughput', percent))

    return controller


def create_if_controller(
    name: str,
    condition: str,
    use_expression: bool = True,
    evaluate_all: bool = False
) -> ET.Element:
    """Create an If Controller element.

    Args:
        name: Controller name
        condition: JavaScript or JMeter expression to evaluate
        use_expression: If True, interpret condition as variable expression
        evaluate_all: If True, evaluate condition for all children
    """
    controller = ET.Element('IfController', {
        'guiclass': 'IfControllerPanel',
        'testclass': 'IfController',
        'testname': name,
        'enabled': 'true'
    })

    controller.append(create_string_prop('IfController.condition', condition))
    controller.append(create_bool_prop('IfController.evaluateAll', evaluate_all))
    controller.append(create_bool_prop('IfController.useExpression', use_expression))

    return controller


def create_loop_controller(
    name: str = "Loop Controller",
    loops: str = "1",
    continue_forever: bool = False
) -> ET.Element:
    """Create a Loop Controller element."""
    controller = ET.Element('LoopController', {
        'guiclass': 'LoopControlPanel',
        'testclass': 'LoopController',
        'testname': name,
        'enabled': 'true'
    })

    controller.append(create_bool_prop('LoopController.continue_forever', continue_forever))
    controller.append(create_string_prop('LoopController.loops', loops))

    return controller


def create_random_controller(name: str = "Random Controller") -> ET.Element:
    """Create a Random Controller element (selects one child randomly)."""
    controller = ET.Element('RandomController', {
        'guiclass': 'RandomControlGui',
        'testclass': 'RandomController',
        'testname': name,
        'enabled': 'true'
    })

    controller.append(create_int_prop('InterleaveControl.style', 1))

    return controller


def create_simple_controller(name: str = "Simple Controller") -> ET.Element:
    """Create a Simple Controller element (just groups elements)."""
    controller = ET.Element('GenericController', {
        'guiclass': 'LogicControllerGui',
        'testclass': 'GenericController',
        'testname': name,
        'enabled': 'true'
    })

    return controller


def create_transaction_controller(
    name: str,
    include_timers: bool = False,
    parent_sample: bool = True
) -> ET.Element:
    """Create a Transaction Controller element."""
    controller = ET.Element('TransactionController', {
        'guiclass': 'TransactionControllerGui',
        'testclass': 'TransactionController',
        'testname': name,
        'enabled': 'true'
    })

    controller.append(create_bool_prop('TransactionController.includeTimers', include_timers))
    controller.append(create_bool_prop('TransactionController.parent', parent_sample))

    return controller
