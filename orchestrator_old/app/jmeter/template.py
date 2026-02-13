"""JMeter test plan (JMX) template manager.

Generates JMX files dynamically based on test configuration.
Supports:
- Template-based generation with variable substitution
- Dynamic thread group configuration
- Multiple sampler types (HTTP, custom)
- Result collector configuration
"""

from dataclasses import dataclass, field
from typing import Optional, List
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass
class HTTPSamplerConfig:
    """Configuration for an HTTP sampler in JMX."""

    name: str
    path: str
    method: str = "GET"
    domain: str = "${TARGET_HOST}"
    port: str = "${TARGET_PORT}"
    protocol: str = "http"
    connect_timeout: int = 5000
    response_timeout: int = 10000
    follow_redirects: bool = True
    use_keepalive: bool = True


@dataclass
class ThreadGroupConfig:
    """Configuration for a thread group in JMX."""

    name: str
    num_threads: str = "${THREAD_COUNT}"
    ramp_time: str = "${RAMP_UP_SEC}"
    duration: str = "${DURATION_SEC}"
    delay: str = "0"
    scheduler: bool = True
    loop_count: int = -1  # -1 = infinite (use duration)
    on_sample_error: str = "continue"


@dataclass
class JMXTestPlanConfig:
    """Configuration for generating a JMX test plan."""

    name: str = "Agent Performance Load Test"
    comments: str = "Generated test plan for agent performance testing"

    # Variables
    target_host: str = "localhost"
    target_port: int = 8080
    thread_count: int = 10
    ramp_up_sec: int = 30
    duration_sec: int = 600
    warmup_sec: int = 60

    # Thread groups
    thread_groups: List[ThreadGroupConfig] = field(default_factory=list)

    # Samplers
    samplers: List[HTTPSamplerConfig] = field(default_factory=list)

    # Options
    include_warmup_group: bool = True
    include_aggregate_report: bool = True
    include_summary_report: bool = True


class JMXTemplateManager:
    """
    Manages JMeter test plan (JMX) generation.

    Generates valid JMX files that can be executed by JMeter.
    Uses XML structure matching JMeter's format.
    """

    # JMeter XML namespaces and versions
    JMETER_VERSION = "5.6.3"
    PROPERTIES_VERSION = "5.0"

    def __init__(self, template_dir: Optional[str] = None):
        """
        Initialize template manager.

        Args:
            template_dir: Directory containing JMX templates (optional)
        """
        self._template_dir = Path(template_dir) if template_dir else None

    def generate_test_plan(self, config: JMXTestPlanConfig) -> str:
        """
        Generate a complete JMX test plan.

        Args:
            config: Test plan configuration

        Returns:
            JMX file content as string
        """
        # Create root element
        root = ET.Element("jmeterTestPlan")
        root.set("version", "1.2")
        root.set("properties", self.PROPERTIES_VERSION)
        root.set("jmeter", self.JMETER_VERSION)

        # Create hash tree structure
        root_hash = ET.SubElement(root, "hashTree")

        # Add test plan
        test_plan = self._create_test_plan(config)
        root_hash.append(test_plan)

        test_plan_hash = ET.SubElement(root_hash, "hashTree")

        # Add user defined variables
        variables = self._create_variables(config)
        test_plan_hash.append(variables)
        test_plan_hash.append(ET.Element("hashTree"))

        # Add warmup thread group if configured
        if config.include_warmup_group:
            warmup_group = self._create_warmup_thread_group(config)
            test_plan_hash.append(warmup_group)
            warmup_hash = ET.SubElement(test_plan_hash, "hashTree")
            self._add_samplers_to_hash(warmup_hash, config.samplers)
            self._add_timer_to_hash(warmup_hash)

        # Add main thread group
        main_group = self._create_main_thread_group(config)
        test_plan_hash.append(main_group)
        main_hash = ET.SubElement(test_plan_hash, "hashTree")
        self._add_samplers_to_hash(main_hash, config.samplers)
        self._add_timer_to_hash(main_hash)

        # Add result collectors
        if config.include_summary_report:
            summary = self._create_summary_report()
            test_plan_hash.append(summary)
            test_plan_hash.append(ET.Element("hashTree"))

        if config.include_aggregate_report:
            aggregate = self._create_aggregate_report()
            test_plan_hash.append(aggregate)
            test_plan_hash.append(ET.Element("hashTree"))

        # Generate XML string
        return self._to_xml_string(root)

    def _create_test_plan(self, config: JMXTestPlanConfig) -> ET.Element:
        """Create TestPlan element."""
        elem = ET.Element("TestPlan")
        elem.set("guiclass", "TestPlanGui")
        elem.set("testclass", "TestPlan")
        elem.set("testname", config.name)
        elem.set("enabled", "true")

        self._add_string_prop(elem, "TestPlan.comments", config.comments)
        self._add_bool_prop(elem, "TestPlan.functional_mode", False)
        self._add_bool_prop(elem, "TestPlan.tearDown_on_shutdown", True)
        self._add_bool_prop(elem, "TestPlan.serialize_threadgroups", False)

        # User defined variables container
        udv = ET.SubElement(elem, "elementProp")
        udv.set("name", "TestPlan.user_defined_variables")
        udv.set("elementType", "Arguments")
        ET.SubElement(udv, "collectionProp").set("name", "Arguments.arguments")

        return elem

    def _create_variables(self, config: JMXTestPlanConfig) -> ET.Element:
        """Create user defined variables element."""
        elem = ET.Element("Arguments")
        elem.set("guiclass", "ArgumentsPanel")
        elem.set("testclass", "Arguments")
        elem.set("testname", "User Defined Variables")
        elem.set("enabled", "true")

        collection = ET.SubElement(elem, "collectionProp")
        collection.set("name", "Arguments.arguments")

        variables = {
            "TARGET_HOST": f"${{__P(TARGET_HOST,{config.target_host})}}",
            "TARGET_PORT": f"${{__P(TARGET_PORT,{config.target_port})}}",
            "THREAD_COUNT": f"${{__P(THREAD_COUNT,{config.thread_count})}}",
            "RAMP_UP_SEC": f"${{__P(RAMP_UP_SEC,{config.ramp_up_sec})}}",
            "DURATION_SEC": f"${{__P(DURATION_SEC,{config.duration_sec})}}",
            "WARMUP_SEC": f"${{__P(WARMUP_SEC,{config.warmup_sec})}}",
        }

        for name, value in variables.items():
            self._add_argument(collection, name, value)

        return elem

    def _add_argument(self, collection: ET.Element, name: str, value: str) -> None:
        """Add an argument to a collection."""
        elem_prop = ET.SubElement(collection, "elementProp")
        elem_prop.set("name", name)
        elem_prop.set("elementType", "Argument")
        self._add_string_prop(elem_prop, "Argument.name", name)
        self._add_string_prop(elem_prop, "Argument.value", value)
        self._add_string_prop(elem_prop, "Argument.metadata", "=")

    def _create_warmup_thread_group(self, config: JMXTestPlanConfig) -> ET.Element:
        """Create warmup thread group."""
        elem = ET.Element("ThreadGroup")
        elem.set("guiclass", "ThreadGroupGui")
        elem.set("testclass", "ThreadGroup")
        elem.set("testname", "Warmup Thread Group")
        elem.set("enabled", "true")

        self._add_string_prop(elem, "ThreadGroup.on_sample_error", "continue")
        self._add_string_prop(elem, "ThreadGroup.num_threads", "${THREAD_COUNT}")
        self._add_string_prop(elem, "ThreadGroup.ramp_time", "${RAMP_UP_SEC}")
        self._add_bool_prop(elem, "ThreadGroup.scheduler", True)
        self._add_string_prop(elem, "ThreadGroup.duration", "${WARMUP_SEC}")
        self._add_string_prop(elem, "ThreadGroup.delay", "0")

        # Loop controller
        loop = ET.SubElement(elem, "elementProp")
        loop.set("name", "ThreadGroup.main_controller")
        loop.set("elementType", "LoopController")
        self._add_bool_prop(loop, "LoopController.continue_forever", False)
        self._add_int_prop(loop, "LoopController.loops", -1)

        return elem

    def _create_main_thread_group(self, config: JMXTestPlanConfig) -> ET.Element:
        """Create main thread group."""
        elem = ET.Element("ThreadGroup")
        elem.set("guiclass", "ThreadGroupGui")
        elem.set("testclass", "ThreadGroup")
        elem.set("testname", "Main Test Thread Group")
        elem.set("enabled", "true")

        self._add_string_prop(elem, "ThreadGroup.on_sample_error", "continue")
        self._add_string_prop(elem, "ThreadGroup.num_threads", "${THREAD_COUNT}")
        self._add_string_prop(elem, "ThreadGroup.ramp_time", "${RAMP_UP_SEC}")
        self._add_bool_prop(elem, "ThreadGroup.scheduler", True)
        self._add_string_prop(elem, "ThreadGroup.duration", "${DURATION_SEC}")
        self._add_string_prop(elem, "ThreadGroup.delay", "${WARMUP_SEC}")

        # Loop controller
        loop = ET.SubElement(elem, "elementProp")
        loop.set("name", "ThreadGroup.main_controller")
        loop.set("elementType", "LoopController")
        self._add_bool_prop(loop, "LoopController.continue_forever", False)
        self._add_int_prop(loop, "LoopController.loops", -1)

        return elem

    def _add_samplers_to_hash(
        self,
        hash_elem: ET.Element,
        samplers: List[HTTPSamplerConfig],
    ) -> None:
        """Add HTTP samplers to a hash tree."""
        # If no samplers configured, add default ones
        if not samplers:
            samplers = [
                HTTPSamplerConfig(name="Health Check", path="/health"),
                HTTPSamplerConfig(name="Status Check", path="/status"),
            ]

        for sampler_config in samplers:
            sampler = self._create_http_sampler(sampler_config)
            hash_elem.append(sampler)
            hash_elem.append(ET.Element("hashTree"))

    def _create_http_sampler(self, config: HTTPSamplerConfig) -> ET.Element:
        """Create an HTTP sampler element."""
        elem = ET.Element("HTTPSamplerProxy")
        elem.set("guiclass", "HttpTestSampleGui")
        elem.set("testclass", "HTTPSamplerProxy")
        elem.set("testname", config.name)
        elem.set("enabled", "true")

        # Arguments
        args = ET.SubElement(elem, "elementProp")
        args.set("name", "HTTPsampler.Arguments")
        args.set("elementType", "Arguments")
        ET.SubElement(args, "collectionProp").set("name", "Arguments.arguments")

        self._add_string_prop(elem, "HTTPSampler.domain", config.domain)
        self._add_string_prop(elem, "HTTPSampler.port", config.port)
        self._add_string_prop(elem, "HTTPSampler.protocol", config.protocol)
        self._add_string_prop(elem, "HTTPSampler.path", config.path)
        self._add_string_prop(elem, "HTTPSampler.method", config.method)
        self._add_bool_prop(elem, "HTTPSampler.follow_redirects", config.follow_redirects)
        self._add_bool_prop(elem, "HTTPSampler.auto_redirects", False)
        self._add_bool_prop(elem, "HTTPSampler.use_keepalive", config.use_keepalive)
        self._add_bool_prop(elem, "HTTPSampler.DO_MULTIPART_POST", False)
        self._add_string_prop(elem, "HTTPSampler.connect_timeout", str(config.connect_timeout))
        self._add_string_prop(elem, "HTTPSampler.response_timeout", str(config.response_timeout))

        return elem

    def _add_timer_to_hash(self, hash_elem: ET.Element) -> None:
        """Add a constant throughput timer."""
        timer = ET.Element("ConstantThroughputTimer")
        timer.set("guiclass", "ConstantThroughputTimerGui")
        timer.set("testclass", "ConstantThroughputTimer")
        timer.set("testname", "Throughput Control")
        timer.set("enabled", "true")

        self._add_int_prop(timer, "calcMode", 2)  # All active threads in current thread group
        self._add_string_prop(timer, "throughput", "600")  # 10 requests per second per thread

        hash_elem.append(timer)
        hash_elem.append(ET.Element("hashTree"))

    def _create_summary_report(self) -> ET.Element:
        """Create summary report result collector."""
        elem = ET.Element("ResultCollector")
        elem.set("guiclass", "SummaryReport")
        elem.set("testclass", "ResultCollector")
        elem.set("testname", "Summary Report")
        elem.set("enabled", "true")

        self._add_bool_prop(elem, "ResultCollector.error_logging", False)
        self._add_save_config(elem)
        self._add_string_prop(elem, "filename", "")

        return elem

    def _create_aggregate_report(self) -> ET.Element:
        """Create aggregate report result collector."""
        elem = ET.Element("ResultCollector")
        elem.set("guiclass", "StatVisualizer")
        elem.set("testclass", "ResultCollector")
        elem.set("testname", "Aggregate Report")
        elem.set("enabled", "true")

        self._add_bool_prop(elem, "ResultCollector.error_logging", False)
        self._add_save_config(elem)
        self._add_string_prop(elem, "filename", "")

        return elem

    def _add_save_config(self, parent: ET.Element) -> None:
        """Add save configuration to a result collector."""
        obj_prop = ET.SubElement(parent, "objProp")
        ET.SubElement(obj_prop, "name").text = "saveConfig"

        value = ET.SubElement(obj_prop, "value")
        value.set("class", "SampleSaveConfiguration")

        save_props = [
            "time", "latency", "timestamp", "success", "label", "code",
            "message", "threadName", "dataType", "assertions", "subresults",
            "bytes", "sentBytes", "url", "threadCounts", "idleTime", "connectTime"
        ]

        for prop in save_props:
            ET.SubElement(value, prop).text = "true"

        false_props = ["encoding", "responseData", "samplerData", "xml",
                       "responseHeaders", "requestHeaders", "responseDataOnError"]
        for prop in false_props:
            ET.SubElement(value, prop).text = "false"

        ET.SubElement(value, "fieldNames").text = "true"
        ET.SubElement(value, "saveAssertionResultsFailureMessage").text = "true"
        ET.SubElement(value, "assertionsResultsToSave").text = "0"

    def _add_string_prop(self, parent: ET.Element, name: str, value: str) -> None:
        """Add a string property."""
        prop = ET.SubElement(parent, "stringProp")
        prop.set("name", name)
        prop.text = value

    def _add_bool_prop(self, parent: ET.Element, name: str, value: bool) -> None:
        """Add a boolean property."""
        prop = ET.SubElement(parent, "boolProp")
        prop.set("name", name)
        prop.text = str(value).lower()

    def _add_int_prop(self, parent: ET.Element, name: str, value: int) -> None:
        """Add an integer property."""
        prop = ET.SubElement(parent, "intProp")
        prop.set("name", name)
        prop.text = str(value)

    def _to_xml_string(self, root: ET.Element) -> str:
        """Convert element tree to XML string."""
        # Add XML declaration
        xml_decl = '<?xml version="1.0" encoding="UTF-8"?>\n'

        # Generate XML string
        xml_str = ET.tostring(root, encoding="unicode")

        return xml_decl + xml_str

    def save_test_plan(self, config: JMXTestPlanConfig, file_path: str) -> str:
        """
        Generate and save a JMX test plan to file.

        Args:
            config: Test plan configuration
            file_path: Path to save the JMX file

        Returns:
            The file path
        """
        content = self.generate_test_plan(config)

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return str(path)


def create_default_test_plan(
    target_host: str,
    target_port: int,
    thread_count: int = 10,
    duration_sec: int = 600,
    warmup_sec: int = 60,
) -> str:
    """
    Create a default test plan for agent performance testing.

    Args:
        target_host: Target server hostname/IP
        target_port: Target server port
        thread_count: Number of concurrent threads
        duration_sec: Test duration in seconds
        warmup_sec: Warmup period in seconds

    Returns:
        JMX file content as string
    """
    config = JMXTestPlanConfig(
        name="Agent Performance Load Test",
        target_host=target_host,
        target_port=target_port,
        thread_count=thread_count,
        duration_sec=duration_sec,
        warmup_sec=warmup_sec,
        samplers=[
            HTTPSamplerConfig(name="Health Check", path="/health"),
            HTTPSamplerConfig(name="Status Check", path="/status"),
            HTTPSamplerConfig(name="Calibration Data", path="/calibration"),
        ],
    )

    manager = JMXTemplateManager()
    return manager.generate_test_plan(config)
