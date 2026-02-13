"""Base JMX XML Element Builders.

Creates common JMeter test plan elements like TestPlan, ThreadGroup, etc.
"""

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional


def create_string_prop(name: str, value: str) -> ET.Element:
    """Create a stringProp element."""
    elem = ET.Element('stringProp', {'name': name})
    elem.text = value
    return elem


def create_bool_prop(name: str, value: bool) -> ET.Element:
    """Create a boolProp element."""
    elem = ET.Element('boolProp', {'name': name})
    elem.text = 'true' if value else 'false'
    return elem


def create_int_prop(name: str, value: int) -> ET.Element:
    """Create an intProp element."""
    elem = ET.Element('intProp', {'name': name})
    elem.text = str(value)
    return elem


def create_long_prop(name: str, value: int) -> ET.Element:
    """Create a longProp element."""
    elem = ET.Element('longProp', {'name': name})
    elem.text = str(value)
    return elem


def create_simple_element(name: str, value: str) -> ET.Element:
    """Create a simple element with text value.

    Used inside SampleSaveConfiguration where JMeter 5.x expects:
    <time>true</time> instead of <boolProp name="time">true</boolProp>
    """
    elem = ET.Element(name)
    elem.text = value
    return elem


def create_name_element(value: str) -> ET.Element:
    """Create a <name>value</name> element.

    Used inside objProp where JMeter 5.x expects:
    <name>saveConfig</name> instead of <stringProp name="name">saveConfig</stringProp>
    """
    elem = ET.Element('name')
    elem.text = value
    return elem


def create_element_prop(name: str, element_type: str) -> ET.Element:
    """Create an elementProp element."""
    return ET.Element('elementProp', {
        'name': name,
        'elementType': element_type
    })


def create_hash_tree() -> ET.Element:
    """Create an empty hashTree element."""
    return ET.Element('hashTree')


def create_test_plan(name: str = "Test Plan") -> ET.Element:
    """Create the root TestPlan element."""
    test_plan = ET.Element('TestPlan', {
        'guiclass': 'TestPlanGui',
        'testclass': 'TestPlan',
        'testname': name,
        'enabled': 'true'
    })

    test_plan.append(create_string_prop('TestPlan.comments', ''))
    test_plan.append(create_bool_prop('TestPlan.functional_mode', False))
    test_plan.append(create_bool_prop('TestPlan.tearDown_on_shutdown', True))
    test_plan.append(create_bool_prop('TestPlan.serialize_threadgroups', False))

    # Element collection
    elem_prop = create_element_prop('TestPlan.user_defined_variables', 'Arguments')
    elem_prop.set('guiclass', 'ArgumentsPanel')
    elem_prop.set('testclass', 'Arguments')
    elem_prop.set('testname', 'User Defined Variables')
    elem_prop.set('enabled', 'true')

    coll_prop = ET.SubElement(elem_prop, 'collectionProp', {'name': 'Arguments.arguments'})
    test_plan.append(elem_prop)

    test_plan.append(create_string_prop('TestPlan.user_define_classpath', ''))

    return test_plan


def create_thread_group(
    name: str = "Thread Group",
    threads: str = "${THREAD_COUNT}",
    ramp_up: str = "${RAMP_UP_SEC}",
    duration: str = "${DURATION_SEC}",
    loops: str = "-1",  # -1 means forever (use duration instead)
    scheduler: bool = True
) -> ET.Element:
    """Create a ThreadGroup element."""
    thread_group = ET.Element('ThreadGroup', {
        'guiclass': 'ThreadGroupGui',
        'testclass': 'ThreadGroup',
        'testname': name,
        'enabled': 'true'
    })

    thread_group.append(create_string_prop('ThreadGroup.on_sample_error', 'continue'))

    # Loop controller
    loop_ctrl = create_element_prop('ThreadGroup.main_controller', 'LoopController')
    loop_ctrl.set('guiclass', 'LoopControlPanel')
    loop_ctrl.set('testclass', 'LoopController')
    loop_ctrl.set('testname', 'Loop Controller')
    loop_ctrl.set('enabled', 'true')
    loop_ctrl.append(create_bool_prop('LoopController.continue_forever', False))
    loop_ctrl.append(create_string_prop('LoopController.loops', loops))
    thread_group.append(loop_ctrl)

    thread_group.append(create_string_prop('ThreadGroup.num_threads', threads))
    thread_group.append(create_string_prop('ThreadGroup.ramp_time', ramp_up))
    thread_group.append(create_bool_prop('ThreadGroup.scheduler', scheduler))
    thread_group.append(create_string_prop('ThreadGroup.duration', duration))
    thread_group.append(create_string_prop('ThreadGroup.delay', ''))
    thread_group.append(create_bool_prop('ThreadGroup.same_user_on_next_iteration', True))

    return thread_group


def create_setup_thread_group(
    name: str = "setUp Thread Group",
    threads: str = "1",
    ramp_up: str = "0",
    loops: str = "1"
) -> ET.Element:
    """Create a setUp Thread Group element.

    setUp Thread Groups run BEFORE all regular Thread Groups.
    Used for initialization tasks like creating test tables, users, etc.
    """
    thread_group = ET.Element('SetupThreadGroup', {
        'guiclass': 'SetupThreadGroupGui',
        'testclass': 'SetupThreadGroup',
        'testname': name,
        'enabled': 'true'
    })

    thread_group.append(create_string_prop('ThreadGroup.on_sample_error', 'continue'))

    # Loop controller - runs once
    loop_ctrl = create_element_prop('ThreadGroup.main_controller', 'LoopController')
    loop_ctrl.set('guiclass', 'LoopControlPanel')
    loop_ctrl.set('testclass', 'LoopController')
    loop_ctrl.set('testname', 'Loop Controller')
    loop_ctrl.set('enabled', 'true')
    loop_ctrl.append(create_bool_prop('LoopController.continue_forever', False))
    loop_ctrl.append(create_string_prop('LoopController.loops', loops))
    thread_group.append(loop_ctrl)

    thread_group.append(create_string_prop('ThreadGroup.num_threads', threads))
    thread_group.append(create_string_prop('ThreadGroup.ramp_time', ramp_up))
    thread_group.append(create_bool_prop('ThreadGroup.scheduler', False))
    thread_group.append(create_string_prop('ThreadGroup.duration', ''))
    thread_group.append(create_string_prop('ThreadGroup.delay', ''))
    thread_group.append(create_bool_prop('ThreadGroup.same_user_on_next_iteration', True))

    return thread_group


def create_teardown_thread_group(
    name: str = "tearDown Thread Group",
    threads: str = "1",
    ramp_up: str = "0",
    loops: str = "1"
) -> ET.Element:
    """Create a tearDown Thread Group element.

    tearDown Thread Groups run AFTER all regular Thread Groups complete.
    Used for cleanup tasks like dropping test tables, users, etc.
    """
    thread_group = ET.Element('PostThreadGroup', {
        'guiclass': 'PostThreadGroupGui',
        'testclass': 'PostThreadGroup',
        'testname': name,
        'enabled': 'true'
    })

    thread_group.append(create_string_prop('ThreadGroup.on_sample_error', 'continue'))

    # Loop controller - runs once
    loop_ctrl = create_element_prop('ThreadGroup.main_controller', 'LoopController')
    loop_ctrl.set('guiclass', 'LoopControlPanel')
    loop_ctrl.set('testclass', 'LoopController')
    loop_ctrl.set('testname', 'Loop Controller')
    loop_ctrl.set('enabled', 'true')
    loop_ctrl.append(create_bool_prop('LoopController.continue_forever', False))
    loop_ctrl.append(create_string_prop('LoopController.loops', loops))
    thread_group.append(loop_ctrl)

    thread_group.append(create_string_prop('ThreadGroup.num_threads', threads))
    thread_group.append(create_string_prop('ThreadGroup.ramp_time', ramp_up))
    thread_group.append(create_bool_prop('ThreadGroup.scheduler', False))
    thread_group.append(create_string_prop('ThreadGroup.duration', ''))
    thread_group.append(create_string_prop('ThreadGroup.delay', ''))
    thread_group.append(create_bool_prop('ThreadGroup.same_user_on_next_iteration', True))

    return thread_group


def create_user_defined_variables(
    name: str = "User Defined Variables",
    variables: Dict[str, str] = None
) -> ET.Element:
    """Create a User Defined Variables (Arguments) element."""
    if variables is None:
        variables = {}

    args = ET.Element('Arguments', {
        'guiclass': 'ArgumentsPanel',
        'testclass': 'Arguments',
        'testname': name,
        'enabled': 'true'
    })

    coll_prop = ET.SubElement(args, 'collectionProp', {'name': 'Arguments.arguments'})

    for var_name, var_value in variables.items():
        elem_prop = ET.SubElement(coll_prop, 'elementProp', {
            'name': var_name,
            'elementType': 'Argument'
        })
        elem_prop.append(create_string_prop('Argument.name', var_name))
        elem_prop.append(create_string_prop('Argument.value', var_value))
        elem_prop.append(create_string_prop('Argument.metadata', '='))

    return args


def create_header_manager(
    name: str = "HTTP Header Manager",
    headers: Dict[str, str] = None
) -> ET.Element:
    """Create an HTTP Header Manager element."""
    if headers is None:
        headers = {'Content-Type': 'application/json'}

    header_mgr = ET.Element('HeaderManager', {
        'guiclass': 'HeaderPanel',
        'testclass': 'HeaderManager',
        'testname': name,
        'enabled': 'true'
    })

    coll_prop = ET.SubElement(header_mgr, 'collectionProp', {'name': 'HeaderManager.headers'})

    for header_name, header_value in headers.items():
        elem_prop = ET.SubElement(coll_prop, 'elementProp', {
            'name': '',
            'elementType': 'Header'
        })
        elem_prop.append(create_string_prop('Header.name', header_name))
        elem_prop.append(create_string_prop('Header.value', header_value))

    return header_mgr


def create_view_results_tree(
    name: str = "View Results Tree",
    enabled: bool = False  # Usually disabled in load tests
) -> ET.Element:
    """Create a View Results Tree listener."""
    listener = ET.Element('ResultCollector', {
        'guiclass': 'ViewResultsFullVisualizer',
        'testclass': 'ResultCollector',
        'testname': name,
        'enabled': 'true' if enabled else 'false'
    })

    listener.append(create_bool_prop('ResultCollector.error_logging', False))

    obj_prop = ET.SubElement(listener, 'objProp')
    obj_prop.append(create_name_element('saveConfig'))

    value = ET.SubElement(obj_prop, 'value', {'class': 'SampleSaveConfiguration'})
    value.append(create_simple_element('time', 'true'))
    value.append(create_simple_element('latency', 'true'))
    value.append(create_simple_element('timestamp', 'true'))
    value.append(create_simple_element('success', 'true'))
    value.append(create_simple_element('label', 'true'))
    value.append(create_simple_element('code', 'true'))
    value.append(create_simple_element('message', 'true'))
    value.append(create_simple_element('threadName', 'true'))
    value.append(create_simple_element('dataType', 'true'))
    value.append(create_simple_element('encoding', 'false'))
    value.append(create_simple_element('assertions', 'true'))
    value.append(create_simple_element('subresults', 'true'))
    value.append(create_simple_element('responseData', 'false'))
    value.append(create_simple_element('samplerData', 'false'))
    value.append(create_simple_element('xml', 'false'))
    value.append(create_simple_element('fieldNames', 'true'))
    value.append(create_simple_element('responseHeaders', 'false'))
    value.append(create_simple_element('requestHeaders', 'false'))
    value.append(create_simple_element('responseDataOnError', 'false'))
    value.append(create_simple_element('saveAssertionResultsFailureMessage', 'true'))
    value.append(create_simple_element('bytes', 'true'))
    value.append(create_simple_element('sentBytes', 'true'))
    value.append(create_simple_element('url', 'true'))
    value.append(create_simple_element('threadCounts', 'true'))
    value.append(create_simple_element('idleTime', 'true'))
    value.append(create_simple_element('connectTime', 'true'))

    listener.append(create_string_prop('filename', ''))

    return listener


def create_summary_report(name: str = "Summary Report") -> ET.Element:
    """Create a Summary Report listener."""
    listener = ET.Element('ResultCollector', {
        'guiclass': 'SummaryReport',
        'testclass': 'ResultCollector',
        'testname': name,
        'enabled': 'true'
    })

    listener.append(create_bool_prop('ResultCollector.error_logging', False))

    obj_prop = ET.SubElement(listener, 'objProp')
    obj_prop.append(create_name_element('saveConfig'))

    value = ET.SubElement(obj_prop, 'value', {'class': 'SampleSaveConfiguration'})
    value.append(create_simple_element('time', 'true'))
    value.append(create_simple_element('latency', 'true'))
    value.append(create_simple_element('timestamp', 'true'))
    value.append(create_simple_element('success', 'true'))
    value.append(create_simple_element('label', 'true'))
    value.append(create_simple_element('code', 'true'))
    value.append(create_simple_element('message', 'true'))
    value.append(create_simple_element('threadName', 'true'))
    value.append(create_simple_element('dataType', 'true'))
    value.append(create_simple_element('encoding', 'false'))
    value.append(create_simple_element('assertions', 'true'))
    value.append(create_simple_element('subresults', 'true'))
    value.append(create_simple_element('responseData', 'false'))
    value.append(create_simple_element('samplerData', 'false'))
    value.append(create_simple_element('xml', 'false'))
    value.append(create_simple_element('fieldNames', 'true'))
    value.append(create_simple_element('responseHeaders', 'false'))
    value.append(create_simple_element('requestHeaders', 'false'))
    value.append(create_simple_element('responseDataOnError', 'false'))
    value.append(create_simple_element('saveAssertionResultsFailureMessage', 'true'))
    value.append(create_simple_element('bytes', 'true'))
    value.append(create_simple_element('sentBytes', 'true'))
    value.append(create_simple_element('url', 'true'))
    value.append(create_simple_element('threadCounts', 'true'))
    value.append(create_simple_element('idleTime', 'true'))
    value.append(create_simple_element('connectTime', 'true'))

    listener.append(create_string_prop('filename', ''))

    return listener


def create_aggregate_report(name: str = "Aggregate Report") -> ET.Element:
    """Create an Aggregate Report listener."""
    listener = ET.Element('ResultCollector', {
        'guiclass': 'StatVisualizer',
        'testclass': 'ResultCollector',
        'testname': name,
        'enabled': 'true'
    })

    listener.append(create_bool_prop('ResultCollector.error_logging', False))

    obj_prop = ET.SubElement(listener, 'objProp')
    obj_prop.append(create_name_element('saveConfig'))

    value = ET.SubElement(obj_prop, 'value', {'class': 'SampleSaveConfiguration'})
    value.append(create_simple_element('time', 'true'))
    value.append(create_simple_element('latency', 'true'))
    value.append(create_simple_element('timestamp', 'true'))
    value.append(create_simple_element('success', 'true'))
    value.append(create_simple_element('label', 'true'))
    value.append(create_simple_element('code', 'true'))
    value.append(create_simple_element('message', 'true'))
    value.append(create_simple_element('threadName', 'true'))
    value.append(create_simple_element('dataType', 'true'))
    value.append(create_simple_element('encoding', 'false'))
    value.append(create_simple_element('assertions', 'true'))
    value.append(create_simple_element('subresults', 'true'))
    value.append(create_simple_element('responseData', 'false'))
    value.append(create_simple_element('samplerData', 'false'))
    value.append(create_simple_element('xml', 'false'))
    value.append(create_simple_element('fieldNames', 'true'))
    value.append(create_simple_element('responseHeaders', 'false'))
    value.append(create_simple_element('requestHeaders', 'false'))
    value.append(create_simple_element('responseDataOnError', 'false'))
    value.append(create_simple_element('saveAssertionResultsFailureMessage', 'true'))
    value.append(create_simple_element('bytes', 'true'))
    value.append(create_simple_element('sentBytes', 'true'))
    value.append(create_simple_element('url', 'true'))
    value.append(create_simple_element('threadCounts', 'true'))
    value.append(create_simple_element('idleTime', 'true'))
    value.append(create_simple_element('connectTime', 'true'))

    listener.append(create_string_prop('filename', ''))

    return listener
