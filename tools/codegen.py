#!/usr/bin/env python
"""Generates the pamqp/specification.py file used as a foundation for AMQP
communication.

"""
import copy
import datetime
import json
import keyword
import pathlib
import sys
import textwrap

import lxml.etree
import requests
from yapf import yapf_api

__author__ = 'Gavin M. Roy'
__email__ = 'gavinmroy@gmail.com'
__since__ = '2011-03-31'

CODEGEN_DIR = pathlib.Path('./codegen/')
CODEGEN_IGNORE_CLASSES = ['access']
CODEGEN_JSON = CODEGEN_DIR / 'amqp-rabbitmq-0.9.1.json'
CODEGEN_XML = CODEGEN_DIR / 'amqp0-9-1.xml'

COMMANDS = pathlib.Path('./pamqp/commands.py')
CONSTANTS = pathlib.Path('./pamqp/constants.py')
EXCEPTIONS = pathlib.Path('./pamqp/exceptions.py')

CODEGEN_JSON_URL = ('https://raw.githubusercontent.com/rabbitmq/'
                    'rabbitmq-codegen/master/amqp-rabbitmq-0.9.1.json')
CODEGEN_XML_URL = 'http://www.rabbitmq.com/resources/specs/amqp0-9-1.xml'

XPATH_ORDER = ['class', 'constant', 'method', 'field']

AMQ_TYPE_TO_ANNOTATION = {
    'bit': 'bool',
    'long': 'int',
    'longlong': 'int',
    'longstr': 'str',
    'octet': 'int',
    'short': 'int',
    'shortstr': 'str',
    'table': 'common.FieldTable',
    'timestamp': 'common.Timestamp',
}


# Output buffer list
output = []


def new_line(text='', indent_value=0, secondary_indent=0):
    """Append a new line to the output buffer"""
    global output

    if not text:
        output.append(text)
        return

    initial = ''.rjust(indent_value)
    secondary = ''.rjust(secondary_indent or indent_value)

    wrapper = textwrap.TextWrapper(
        width=79, drop_whitespace=True, initial_indent=initial,
        subsequent_indent=secondary)

    for value in wrapper.wrap(text.rstrip()):
        output.append(value)


def classify(text):
    """Replace the AMQP constant with a more pythonic classname"""
    parts = text.split('-')
    value = ''
    for part in parts:
        value += part.title()
    return value


def comment(text, indent_value=0, prefix='# '):
    """Append a comment to the output buffer"""
    for value in get_comments(text, indent_value + len(prefix), prefix):
        new_line(value)


def get_comments(text, indent_value=0, prefix='# '):
    """Return a list of lines for a given comment with the comment prefix"""
    indent_text = prefix.rjust(indent_value)
    values = []
    for value in textwrap.wrap(text, 79 - len(indent_text)):
        values.append(indent_text + value)
    return values


def dashify(text):
    """Replace a - with a _ for the passed in text"""
    return text.replace('-', '_')


def pep8_class_name(value):
    """Returns a class name in the proper case per PEP8"""
    return_value = []
    parts = value.split('-')
    for part in parts:
        return_value.append(part[0:1].upper() + part[1:])
    return ''.join(return_value)


def get_class_definition(cls_name, cls_list):
    """Iterates through class_list trying to match the name against what was
    passed in.

    """
    for cls_def in cls_list:
        if cls_def['name'] == cls_name:
            return cls_def


def get_documentation(search_path):
    """Find the documentation in the xpath

    :param search_path:
    :return:
    """
    search = []
    for k in XPATH_ORDER:
        if k in search_path:
            search.append('%s[@name="%s"]' % (k, search_path[k]))

    node = xml.xpath('%s/doc' % '/'.join(search))

    # Did we not find it? Look for a RabbitMQ extension
    if not node:
        node = rabbitmq.xpath('%s/doc' % '/'.join(search))

    # Look for RabbitMQ extensions of methods
    if not node and 'field' in search_path:
        node = rabbitmq.xpath('field[@name="%s"]/doc' % search_path['method'])

    # Look for RabbitMQ extensions of fields
    if not node and 'field' in search_path:
        node = rabbitmq.xpath('field[@name="%s"]/doc' % search_path['field'])

    # if we found it, strip all the whitespace
    if node:
        return ' '.join([l.strip() for l in node[0].text.split('\n')]).strip()


def get_label(search_path):
    """Look to see if documented & if so, provide the doc as a comment

    :param search_path:
    :return:

    """
    search = []
    for k in XPATH_ORDER:
        if k in search_path:
            search.append('%s[@name="%s"]' % (k, search_path[k]))

    node = xml.xpath('%s' % '/'.join(search))

    if not node:
        node = rabbitmq.xpath('%s' % '/'.join(search))

    # Did it have a value by default?
    if node and 'label' in node[0].attrib:
        return (node[0].attrib['label'][0:1].upper() +
                node[0].attrib['label'][1:])
    elif node and node[0].text:
        return (node[0].text.strip()[0:1].upper() +
                node[0].text.strip()[1:].strip())

    # Look in domains
    if 'field' in search_path:
        node = xml.xpath('//amqp/domain[@name="%s"]' % search_path['field'])
        if node and 'label' in node[0].attrib:
            return (node[0].attrib['label'][0:1].upper() +
                    node[0].attrib['label'][1:])

    # Look for RabbitMQ extensions of fields
    if 'field' in search_path:
        node = rabbitmq.xpath('field[@name="%s"]' % search_path['field'])
        if node and 'label' in node[0].attrib:
            return (node[0].attrib['label'][0:1].upper() +
                    node[0].attrib['label'][1:])
        elif node and node[0].text:
            return (node[0].text.strip()[0:1].upper() +
                    node[0].text.strip()[1:].strip())

    print('Label could not find %r' % search_path)


def argument_name(n):
    """Returns a valid python argument name for the AMQP argument passed in

    :param str n: The argument name

    """
    value = n.replace('-', '_')
    if value in keyword.kwlist:
        value += '_'
    return value


def get_argument_type(a: dict) -> str:
    """Get the argument type"""
    if 'domain' in a:
        for d, dt in amqp['domains']:
            if a['domain'] == d:
                a['type'] = dt
                break
    if 'type' in a:
        return a['type']
    raise ValueError('Unknown argument type')


def arg_annotation(a: dict) -> str:
    arg_type = AMQ_TYPE_TO_ANNOTATION[get_argument_type(a)]
    if arg_type.startswith('common.Field'):
        return 'typing.Optional[{}]'.format(arg_type)
    return arg_type


def arg_default(a: dict) -> str:
    arg_type = AMQ_TYPE_TO_ANNOTATION[get_argument_type(a)]
    if arg_type.startswith('common.Field'):
        return 'None'
    elif a.get('default-value') is not None:
        return '{!r}'.format(a['default-value'])
    else:
        print(a)
        if a['type'][-3:] == 'str':
            return "''"
        elif a['type'] in ['short', 'long']:
            return '0'
        else:
            return 'None'


def new_function(function_name: str, args_in: list, indent_value: int = 0):
    """Create a new function"""
    args = ['self']
    for a in args_in:
        args.append('{}: {} = {}'.format(
            argument_name(a['name']), arg_annotation(a), arg_default(a)))

    # Get the definition line built
    def_line = 'def %s(%s):' % (function_name, ', '.join(args))

    # Build the output of it with wrapping
    indent_str = ''.join(
        [' ' for _x in range(indent_value + len(function_name) + 5)])
    lines = textwrap.wrap(
        ''.join([' ' for _x in range(indent_value)]) + def_line, 79,
        subsequent_indent=indent_str)

    for l in lines:
        new_line(l)


# Check to see if we have the codegen json file in this directory
if CODEGEN_JSON.exists():
    print('Downloading codegen JSON file to %s.' % CODEGEN_JSON)
    response = requests.get(CODEGEN_JSON_URL)
    if not response.ok:
        print('Error downloading JSON file: {}'.format(response))
        sys.exit(1)
    with CODEGEN_JSON.open('w') as handle:
        handle.write(response.content.decode('utf-8'))

with CODEGEN_JSON.open('r') as handle:
    amqp = json.load(handle)

# Check to see if we have the codegen xml file in this directory
if CODEGEN_XML.exists():
    print('Downloading codegen XML file.')
    response = requests.get(CODEGEN_XML_URL)
    if not response.ok:
        print('Error downloading XML file: {}'.format(response))
        sys.exit(1)
    with CODEGEN_XML.open('w') as handle:
        handle.write(response.content.decode('utf-8'))

with CODEGEN_XML.open('r') as handle:
    amqp_xml = lxml.etree.parse(handle)
    xml = amqp_xml.xpath('//amqp')[0]

# RabbitMQ Extension XML file for comments
with open(CODEGEN_DIR / 'extensions.xml', 'r') as handle:
    rabbitmq_xml = lxml.etree.parse(handle)
    rabbitmq = rabbitmq_xml.xpath('//rabbitmq')[0]

# pamqp.constants
output = ['''"""
AMQP Constants
==============

"""
# Auto-generated, do not edit this file. To Generate run `./tools/codegen.py`
''']
comment('AMQP Protocol Frame Prefix')  # AMQP Version Header
new_line("AMQP = b'AMQP'")
new_line()

comment('AMQP Protocol Version')  # AMQP Version Header
new_line('VERSION = ({}, {}, {})'.format(
    amqp['major-version'], amqp['minor-version'], amqp['revision']))
new_line()

# Defaults
comment('RabbitMQ Defaults')
new_line("DEFAULT_HOST = 'localhost'")
new_line('DEFAULT_PORT = {}'.format(amqp['port']))
new_line("DEFAULT_USER = 'guest'")
new_line("DEFAULT_PASS = 'guest'")
new_line("DEFAULT_VHOST = '/'")
new_line()

# Constant
comment('AMQP Constants')
for constant in amqp['constants']:
    if 'class' not in constant:
        # Look to see if documented & if so, provide the doc as a comment
        doc = get_documentation({'constant': constant['name'].lower()})
        if doc:
            comment(doc)
        new_line('{} = {}'.format(dashify(constant['name']), constant['value']))
new_line()

comment('Not included in the spec XML or JSON files.')
new_line("FRAME_END_CHAR = b'\\xce'")
new_line('FRAME_HEADER_SIZE = 7')
new_line('FRAME_MAX_SIZE = 131072')
new_line()

# Data types
data_types = []
domains = []
for domain, data_type in amqp['domains']:
    if domain == data_type:
        data_types.append("              '{}',".format(domain))
    else:
        doc = get_documentation({'domain': domain})
        if doc:
            comments = get_comments(doc, 18)
            for line in comments:
                domains.append(line)
        domains.append("           '{}': '{}',".format(domain, data_type))

comment('AMQP data types')
data_types[0] = data_types[0].replace('              ', 'DATA_TYPES = [')
data_types[-1] = data_types[-1].replace(',', ']')
output += data_types
new_line()

comment('AMQP domains')
domains[0] = domains[0].replace('           ', 'DOMAINS = {')
domains[-1] = domains[-1].replace(',', '}')
output += domains
new_line()

comment('Other constants')

# Deprecation Warning
AMQP_VERSION = ('-'.join([str(amqp['major-version']),
                          str(amqp['minor-version']),
                          str(amqp['revision'])]))
DEPRECATION_WARNING = 'This command is deprecated in AMQP {}'.format(
        AMQP_VERSION)
new_line("DEPRECATION_WARNING = '{}'".format(DEPRECATION_WARNING))
new_line()

code = yapf_api.FormatCode('\n'.join(output), style_config='pep8')
with CONSTANTS.open('w') as handle:
    handle.write(code[0])


# pamqp.exceptions

output = ['''"""
AMQP Exceptions
===============

"""
# Auto-generated, do not edit this file. To Generate run `./tools/codegen.py`


class PAMQPException(Exception):
    """Base exception for all pamqp specific exceptions."""


class UnmarshalingException(PAMQPException):
    """Raised when a frame is not able to be unmarshaled."""
    def __str__(self):  # pragma: nocover
        return 'Could not unmarshal {} frame: {}'.format(
            self.args[0], self.args[1])


class AMQPError(PAMQPException):
    """Base exception for all AMQP errors."""


class AMQPSoftError(AMQPError):
    """Base exception for all AMQP soft errors."""


class AMQPHardError(AMQPError):
    """Base exception for all AMQP hard errors."""

''']

errors = {}
for constant in amqp['constants']:
    if 'class' in constant:
        class_name = classify(constant['name'])
        if constant['class'] == 'soft-error':
            extends = 'AMQPSoftError'
        elif constant['class'] == 'hard-error':
            extends = 'AMQPHardError'
        else:
            raise ValueError('Unexpected class: %s', constant['class'])
        new_line('class AMQP{}({}):'.format(class_name, extends))
        new_line('    """')
        # Look to see if documented & if so, provide the doc as a comment
        doc = get_documentation({'constant': constant['name'].lower()})
        if doc:
            comment(doc, 4, '')
        else:
            if extends == 'AMQPSoftError':
                new_line('    Undocumented AMQP Soft Error')
            else:
                new_line('    Undocumented AMQP Hard Error')
        new_line()
        new_line('    """')
        new_line("    name = '%s'" % constant['name'])
        new_line('    value = %i' % constant['value'])
        new_line()
        new_line()
        errors[constant['value']] = class_name

# Error mapping to class
error_lines = []
for error_code in errors.keys():
    error_lines.append(
        '          {}: AMQP{},'.format(error_code, errors[error_code]))
comment('AMQP Error code to class mapping')
error_lines[0] = error_lines[0].replace('          ', 'CLASS_MAPPING = {')
error_lines[-1] = error_lines[-1].replace(',', '}')
output += error_lines


code = yapf_api.FormatCode('\n'.join(output), style_config='pep8')
with EXCEPTIONS.open('w') as handle:
    handle.write(code[0])


# pamqp.methods

output = ['''"""
AMQP Classes & Methods
======================

"""
# Auto-generated, do not edit this file. To Generate run `./tools/codegen.py`

import typing
import warnings

from pamqp import base, common, constants
''']

# Get the pamqp class list so we can sort it
class_list = []
for amqp_class in amqp['classes']:
    if amqp_class['name'] not in CODEGEN_IGNORE_CLASSES:
        class_list.append(amqp_class['name'])


for class_name in class_list:

    indent = 4

    # Get the class from our JSON file
    definition = get_class_definition(class_name, amqp['classes'])
    new_line()
    new_line('class %s:' % pep8_class_name(class_name))

    doc = get_documentation({'class': class_name})
    label = get_label({'class': class_name}) or 'Undefined label'
    if doc:
        new_line('"""' + label, indent)
        new_line()
        comment(doc, indent, '')
        new_line()
        new_line('"""', indent)

    new_line('__slots__ = []', indent)
    new_line()
    comment('AMQP Class Number and Mapping Index', indent)
    new_line('frame_id = %i' % definition['id'], indent)
    new_line('index = 0x%08X' % (definition['id'] << 16), indent)
    new_line()

    # We use this later down in methods to get method xml to look for stuff
    # that is not in the JSON spec file beyond docs
    class_xml = xml.xpath('//amqp/class[@name="%s"]' % class_name)

    # Build the list of methods
    methods = []
    for method in definition['methods']:
        new_line('class %s(base.Frame):' %
                 pep8_class_name(method['name']), indent)
        indent += 4

        # No Confirm in AMQP spec
        if class_xml:
            doc = get_documentation({'class': class_name,
                                     'method': method['name']})
            label = get_label({'class': class_name,
                               'method': method['name']}) or 'Undefined label'
            if doc:
                new_line('"""%s' % label, indent)
                new_line()
                comment(doc, indent, '')
                new_line()
                new_line('"""', indent)

        # Get the method's XML node
        method_xml = None
        if class_xml:
            method_xml = class_xml[0].xpath('method[@name="%s"]' %
                                            method['name'])

        comment('AMQP Method Number and Mapping Index', indent)
        new_line('frame_id = %i' % method['id'], indent)
        index_value = definition['id'] << 16 | method['id']
        new_line('index = 0x%08X' % index_value, indent)
        new_line("name = '%s.%s'" % (pep8_class_name(class_name),
                                     pep8_class_name(method['name'])),
                 indent)
        # Add an attribute that signifies if it's a sync command
        new_line()
        comment('Specifies if this is a synchronous AMQP method', indent)
        new_line('synchronous = %s' % method.get('synchronous', False),
                 indent)

        # Add an attribute that signifies if it's a sync command
        if method.get('synchronous'):
            responses = []
            if method_xml:
                for response in method_xml[0].iter('response'):

                    response_name = "'%s.%s'" %\
                                    (pep8_class_name(class_name),
                                     pep8_class_name(response.attrib['name']))
                    responses.append(response_name)
            if not responses:
                responses.append("'%s.%sOk'" %
                                 (pep8_class_name(class_name),
                                  pep8_class_name(method['name'])))
            new_line()
            comment('Valid responses to this method', indent)
            new_line('valid_responses = [%s]' % ', '.join(responses),
                     indent)
        new_line()

        arguments = []
        type_keyword = False

        if method['arguments']:
            comment('AMQ Method Attributes', indent)
            new_line('__slots__ = [', indent)
            for arg in method['arguments']:
                name = argument_name(arg['name'])
                if name == 'type' and class_name == 'exchange':
                    name = 'exchange_type'
                if arg == method['arguments'][-1]:
                    new_line('{!r}'.format(name), indent + 4)
                else:
                    new_line('{!r},'.format(name), indent + 4)
            new_line(']', indent)
            new_line()

            comment('Attribute Typing', indent)
            new_line('__annotations__ = {', indent)
            for arg in method['arguments']:
                name = argument_name(arg['name'])
                if name == 'type' and class_name == 'exchange':
                    name = 'exchange_type'
                if arg == method['arguments'][-1]:
                    new_line("{!r}: {}".format(name, arg_annotation(arg)),
                             indent + 4)
                else:
                    new_line("{!r}: {},".format(name, arg_annotation(arg)),
                             indent + 4)
            new_line('}', indent)
            new_line()

            comment('Attribute AMQ Types', indent)
            for argument in method['arguments']:
                name = argument_name(argument['name'])
                if name == 'type' and class_name == 'exchange':
                    name = 'exchange_type'
                new_line(
                    "_{} = '{}'".format(name, get_argument_type(argument)),
                    indent)
            new_line()

        # Function definition
        arguments = copy.deepcopy(method['arguments'])
        for offset in range(0, len(arguments)):
            if arguments[offset]['name'] == 'type' and \
                    class_name == 'exchange':
                arguments[offset]['name'] = 'exchange_type'

        if arguments:
            new_function('__init__', arguments, indent)
            indent += 4
            new_line('"""Initialize the %s.%s class' %
                     (pep8_class_name(class_name),
                      pep8_class_name(method['name'])),
                     indent)

            if type_keyword:
                new_line()
                new_line('Note that the AMQP type argument is referred to as '
                         '"%s_type" ' % class_name, indent)
                new_line('to not conflict with the Python type keyword.',
                         indent)

            # List the arguments in the docblock
            new_line()
            for argument in method['arguments']:
                name = argument_name(argument['name'])
                if name == 'type' and class_name == 'exchange':
                    name = 'exchange_type'
                label = get_label({'class': class_name,
                                   'method': method['name'],
                                   'field': argument['name']})
                if label:
                    new_line(':param {}: {}'.format(name, label),
                             indent, indent + 4)
                else:
                    new_line(':param {}:'.format(argument['name']),
                             indent, indent + 4)

            # Note the deprecation warning in the docblock
            if method_xml and 'deprecated' in method_xml[0].attrib and \
               method_xml[0].attrib['deprecated']:
                deprecated = True
                new_line()
                new_line(
                    '.. deprecated:: %s' % AMQP_VERSION, indent)
                new_line(DEPRECATION_WARNING, indent + 4)
            else:
                deprecated = False

            new_line()
            new_line('"""', indent)

            # Create assignments from the arguments to attributes of the object
            for argument in method['arguments']:
                name = argument_name(argument['name'])

                if name == 'type' and class_name == 'exchange':
                    name = 'exchange_type'

                doc = get_label({'class': class_name,
                                 'method': method['name'],
                                 'field': argument['name']})
                if doc:
                    if argument != method['arguments'][0]:
                        new_line()
                    comment(doc, indent)
                if (isinstance(argument.get('default-value'), dict) and
                        not argument.get('default-value')):
                    new_line('self.%s = %s or {}' % (name, name), indent)
                else:
                    new_line('self.%s = %s' % (name, name), indent)
            new_line()

            # Check if we're deprecated and warn if so
            if deprecated:
                comment(DEPRECATION_WARNING, indent)
                new_line('warnings.warn(constants.DEPRECATION_WARNING, '
                         'category=DeprecationWarning)', indent)
                new_line()

            # End of function
            indent -= 4

        # End of class
        indent -= 4

    if 'properties' in definition and definition['properties']:
        new_line('class Properties(base.BasicProperties):', indent)
        indent += 4
        comment('"""Content Properties"""', indent, '')
        new_line()

        new_line("name = '%s.Properties'" % pep8_class_name(class_name),
                 indent)
        new_line()

        new_line("__slots__ = ['%s'," %
                 argument_name(definition['properties'][0]['name']),
                 indent)
        for argument in definition['properties'][1:-1]:
            name = argument_name(argument['name'])
            if name == 'type':
                name = 'message_type'
            new_line("'%s'," % name, indent + 13)
        new_line("'%s']" % argument_name(definition['properties'][-1]['name']),
                 indent + 13)
        new_line()

        comment('Flag Values', indent)
        flag_value = 15
        new_line("flags = {'%s': %i," %
                 (argument_name(definition['properties'][0]['name']),
                  1 << flag_value), indent)
        for argument in definition['properties'][1:-1]:
            name = argument_name(argument['name'])
            if name == 'type':
                name = 'message_type'
            flag_value -= 1
            new_line("'%s': %i," % (name, 1 << flag_value), indent + 9),
        flag_value -= 1
        new_line("'%s': %i}" %
                 (argument_name(definition['properties'][-1]['name']),
                  1 << flag_value), indent + 9)
        new_line()

        comment('Class Attribute Types', indent)
        for argument in definition['properties']:
            name = argument_name(argument['name'])
            if name == 'type':
                name = 'message_type'
            new_line("_%s = '%s'" % (name, get_argument_type(argument)),
                     indent)
        new_line()
        new_line('frame_id = %i' % definition['id'], indent)
        new_line('index = 0x%04X' % definition['id'], indent)
        new_line()

        # Function definition
        properties = copy.deepcopy(definition['properties'])
        for offset in range(0, len(properties)):
            if properties[offset]['name'] == 'type':
                properties[offset]['name'] = 'message_type'

        new_function('__init__', properties, indent)
        indent += 4
        new_line('"""Initialize the %s.Properties class' %
                 pep8_class_name(class_name),
                 indent)
        new_line()
        new_line('Note that the AMQP property type is named message_type as '
                 'to ', indent)
        new_line('not conflict with the Python type keyword', indent)
        # List the arguments in the docblock
        new_line()
        for argument in definition['properties']:
            name = argument_name(argument['name'])
            if name == 'type':
                name = 'message_type'
            label = get_label({'class': class_name, 'field': argument['name']})
            if label:
                line = ':param {}: {}'.format(name, label or '')
                new_line(line.strip(), indent)

        new_line()
        new_line('"""', indent)

        # Create assignments from the arguments to attributes of the object
        for argument in definition['properties']:
            name = argument_name(argument['name'])
            if name == 'type':
                name = 'message_type'
            doc = get_label({'class': class_name,
                             'field': argument['name']})
            if doc:
                comment(doc, indent)

            new_line('self.%s = %s' % (name, name), indent)
            new_line()

        # End of function
        indent -= 4

new_line()
comment('AMQP Class.Method Index Mapping')
mapping = []
for amqp_class in amqp['classes']:
    if amqp_class['name'] not in CODEGEN_IGNORE_CLASSES:
        for method in amqp_class['methods']:
            key = amqp_class['id'] << 16 | method['id']
            mapping.append(('                 0x%08X: %s.%s,' %
                            (key,
                             pep8_class_name(amqp_class['name']),
                             pep8_class_name(method['name']))))
mapping[0] = mapping[0].replace('                 ',
                                'INDEX_MAPPING = {')
mapping[-1] = mapping[-1].replace(',', '}')
output += mapping
new_line()

code = yapf_api.FormatCode('\n'.join(output), style_config='pep8')
with COMMANDS.open('w') as handle:
    handle.write(code[0])
