"""HTTP Request Sampler Element Builders.

Creates HTTP Request elements for calling emulator endpoints.
"""

import xml.etree.ElementTree as ET
from .base import create_string_prop, create_bool_prop, create_element_prop


def create_http_defaults(
    name: str = "HTTP Request Defaults",
    protocol: str = "http",
    host: str = "${TARGET_HOST}",
    port: str = "${TARGET_PORT}",
    content_encoding: str = "UTF-8"
) -> ET.Element:
    """Create an HTTP Request Defaults element."""
    defaults = ET.Element('ConfigTestElement', {
        'guiclass': 'HttpDefaultsGui',
        'testclass': 'ConfigTestElement',
        'testname': name,
        'enabled': 'true'
    })

    elem_prop = create_element_prop('HTTPsampler.Arguments', 'Arguments')
    elem_prop.set('guiclass', 'HTTPArgumentsPanel')
    elem_prop.set('testclass', 'Arguments')
    elem_prop.set('testname', 'User Defined Variables')
    elem_prop.set('enabled', 'true')
    elem_prop.append(ET.Element('collectionProp', {'name': 'Arguments.arguments'}))
    defaults.append(elem_prop)

    defaults.append(create_string_prop('HTTPSampler.domain', host))
    defaults.append(create_string_prop('HTTPSampler.port', port))
    defaults.append(create_string_prop('HTTPSampler.protocol', protocol))
    defaults.append(create_string_prop('HTTPSampler.contentEncoding', content_encoding))
    defaults.append(create_string_prop('HTTPSampler.path', ''))
    defaults.append(create_string_prop('HTTPSampler.concurrentPool', '6'))
    defaults.append(create_string_prop('HTTPSampler.connect_timeout', ''))
    defaults.append(create_string_prop('HTTPSampler.response_timeout', ''))

    return defaults


def create_http_sampler(
    name: str,
    path: str,
    method: str = "POST",
    body: str = "",
    host: str = "",  # Empty = use defaults
    port: str = "",  # Empty = use defaults
    protocol: str = "",  # Empty = use defaults
    content_type: str = "application/json"
) -> ET.Element:
    """Create an HTTP Request Sampler element.

    Args:
        name: Sampler name (displayed in JMeter)
        path: URL path (e.g., /api/v1/operations/cpu)
        method: HTTP method (GET, POST, PUT, DELETE)
        body: Request body (for POST/PUT)
        host: Target host (optional, uses defaults if empty)
        port: Target port (optional, uses defaults if empty)
        protocol: Protocol (optional, uses defaults if empty)
        content_type: Content-Type header value
    """
    sampler = ET.Element('HTTPSamplerProxy', {
        'guiclass': 'HttpTestSampleGui',
        'testclass': 'HTTPSamplerProxy',
        'testname': name,
        'enabled': 'true'
    })

    # Arguments (body data)
    elem_prop = create_element_prop('HTTPsampler.Arguments', 'Arguments')
    elem_prop.set('guiclass', 'HTTPArgumentsPanel')
    elem_prop.set('testclass', 'Arguments')
    elem_prop.set('testname', 'User Defined Variables')
    elem_prop.set('enabled', 'true')

    coll_prop = ET.SubElement(elem_prop, 'collectionProp', {'name': 'Arguments.arguments'})

    if body:
        # For JSON body, we use a single argument with no name
        arg_prop = ET.SubElement(coll_prop, 'elementProp', {
            'name': '',
            'elementType': 'HTTPArgument'
        })
        arg_prop.append(create_bool_prop('HTTPArgument.always_encode', False))
        arg_prop.append(create_string_prop('Argument.value', body))
        arg_prop.append(create_string_prop('Argument.metadata', '='))
        arg_prop.append(create_bool_prop('HTTPArgument.use_equals', True))
        arg_prop.append(create_string_prop('Argument.name', ''))

    sampler.append(elem_prop)

    sampler.append(create_string_prop('HTTPSampler.domain', host))
    sampler.append(create_string_prop('HTTPSampler.port', port))
    sampler.append(create_string_prop('HTTPSampler.protocol', protocol))
    sampler.append(create_string_prop('HTTPSampler.contentEncoding', 'UTF-8'))
    sampler.append(create_string_prop('HTTPSampler.path', path))
    sampler.append(create_string_prop('HTTPSampler.method', method))
    sampler.append(create_bool_prop('HTTPSampler.follow_redirects', True))
    sampler.append(create_bool_prop('HTTPSampler.auto_redirects', False))
    sampler.append(create_bool_prop('HTTPSampler.use_keepalive', True))
    sampler.append(create_bool_prop('HTTPSampler.DO_MULTIPART_POST', False))
    sampler.append(create_string_prop('HTTPSampler.embedded_url_re', ''))
    sampler.append(create_string_prop('HTTPSampler.connect_timeout', ''))
    sampler.append(create_string_prop('HTTPSampler.response_timeout', ''))

    # For POST with body, set body data flag
    if body and method in ('POST', 'PUT', 'PATCH'):
        sampler.append(create_bool_prop('HTTPSampler.postBodyRaw', True))

    return sampler


# Pre-defined emulator endpoint samplers

def create_cpu_sampler(
    name: str = "CPU Load",
    duration_ms: int = 100,
    intensity: float = 0.7
) -> ET.Element:
    """Create HTTP sampler for CPU operation."""
    body = f'{{"duration_ms": {duration_ms}, "intensity": {intensity}}}'
    return create_http_sampler(
        name=name,
        path="/api/v1/operations/cpu",
        method="POST",
        body=body
    )


def create_memory_sampler(
    name: str = "Memory Load",
    duration_ms: int = 100,
    size_mb: int = 10,
    pattern: str = "random"
) -> ET.Element:
    """Create HTTP sampler for Memory operation."""
    body = f'{{"duration_ms": {duration_ms}, "size_mb": {size_mb}, "pattern": "{pattern}"}}'
    return create_http_sampler(
        name=name,
        path="/api/v1/operations/mem",
        method="POST",
        body=body
    )


def create_disk_sampler(
    name: str = "Disk Load",
    duration_ms: int = 100,
    mode: str = "mixed",
    size_mb: int = 10,
    block_size_kb: int = 64
) -> ET.Element:
    """Create HTTP sampler for Disk operation."""
    body = f'{{"duration_ms": {duration_ms}, "mode": "{mode}", "size_mb": {size_mb}, "block_size_kb": {block_size_kb}}}'
    return create_http_sampler(
        name=name,
        path="/api/v1/operations/disk",
        method="POST",
        body=body
    )


def create_file_sampler(
    name: str = "File Operation",
    is_confidential: str = "${is_confidential}",
    make_zip: str = "${make_zip}",
    size_bracket: str = "${size_bracket}",
    target_size_kb: str = "${target_size_kb}",
    output_format: str = "${output_format}",
    output_folder_idx: str = "${output_folder_idx}",
    source_file_ids: str = "${source_file_ids}",
) -> ET.Element:
    """Create HTTP sampler for File operation.

    All parameters are JMeter variables populated from the ops_sequence CSV.
    The emulator uses these to produce deterministic file operations across
    base and initial test phases.
    """
    body = (
        '{"is_confidential": ' + is_confidential
        + ', "make_zip": ' + make_zip
        + ', "size_bracket": "' + size_bracket + '"'
        + ', "target_size_kb": ' + target_size_kb
        + ', "output_format": "' + output_format + '"'
        + ', "output_folder_idx": ' + output_folder_idx
        + ', "source_file_ids": "' + source_file_ids + '"'
        + '}'
    )
    return create_http_sampler(
        name=name,
        path="/api/v1/operations/file",
        method="POST",
        body=body
    )


def create_anomaly_cpu_sampler(
    name: str = "Anomaly - High CPU",
    duration_ms: int = 5000,
    intensity: float = 1.0
) -> ET.Element:
    """Create HTTP sampler for anomaly CPU operation (high intensity, long duration)."""
    body = f'{{"duration_ms": {duration_ms}, "intensity": {intensity}}}'
    return create_http_sampler(
        name=name,
        path="/api/v1/operations/cpu",
        method="POST",
        body=body
    )
