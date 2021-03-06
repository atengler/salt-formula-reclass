# -*- coding: utf-8 -*-
'''
Module for handling reclass metadata models.

'''

from __future__ import absolute_import

import io
import json
import logging
import os
import sys
import six
import yaml

from reclass import get_storage, output
from reclass.core import Core
from reclass.config import find_and_read_configfile
from string import Template

LOG = logging.getLogger(__name__)


def __virtual__():
    '''
    Only load this module if reclass
    is installed on this minion.
    '''
    return 'reclass'


def _get_nodes_dir():
    defaults = find_and_read_configfile()
    return os.path.join(defaults.get('inventory_base_uri'), 'nodes')


def _get_classes_dir():
    defaults = find_and_read_configfile()
    return os.path.join(defaults.get('inventory_base_uri'), 'classes')


def _get_cluster_dir():
    classes_dir = _get_classes_dir()
    return os.path.join(classes_dir, 'cluster')


def _get_node_meta(name, cluster="default", environment="prd", classes=None, parameters=None):
    host_name = name.split('.')[0]
    domain_name = '.'.join(name.split('.')[1:])

    if classes == None:
        meta_classes = []
    else:
        if isinstance(classes, six.string_types):
            meta_classes = json.loads(classes)
        else:
            meta_classes = classes

    if parameters == None:
        meta_parameters = {}
    else:
        if isinstance(parameters, six.string_types):
            meta_parameters = json.loads(parameters)
        else:
            # generate dict from OrderedDict
            meta_parameters = {k: v for (k, v) in parameters.items()}

    node_meta = {
        'classes': meta_classes,
        'parameters': {
            '_param': meta_parameters,
            'linux': {
                'system': {
                    'name': host_name,
                    'domain': domain_name,
                    'cluster': cluster,
                    'environment': environment,
                }
            }
        }
    }

    return node_meta


def node_create(name, path=None, cluster="default", environment="prd", classes=None, parameters=None, **kwargs):
    '''
    Create a reclass node

    :param name: new node FQDN
    :param path: custom path in nodes for new node
    :param classes: classes given to the new node
    :param parameters: parameters given to the new node
    :param environment: node's environment
    :param cluster: node's cluster

    CLI Examples:

    .. code-block:: bash

        salt '*' reclass.node_create server.domain.com classes=[system.neco1, system.neco2]
        salt '*' reclass.node_create namespace/test enabled=False
    
    '''
    ret = {}

    node = node_get(name=name)

    if node and not "Error" in node:
        LOG.debug("node {0} exists".format(name))
        ret[name] = node
        return ret

    host_name = name.split('.')[0]
    domain_name = '.'.join(name.split('.')[1:])

    node_meta = _get_node_meta(name, cluster, environment, classes, parameters)
    LOG.debug(node_meta)

    if path == None:
        file_path = os.path.join(_get_nodes_dir(), name + '.yml')
    else:
        file_path = os.path.join(_get_nodes_dir(), path, name + '.yml')

    with open(file_path, 'w') as node_file:
        node_file.write(yaml.safe_dump(node_meta, default_flow_style=False))

    return node_get(name)


def node_delete(name, **kwargs):
    '''
    Delete a reclass node

    :params node: Node name

    CLI Examples:

    .. code-block:: bash

        salt '*' reclass.node_delete demo01.domain.com
        salt '*' reclass.node_delete name=demo01.domain.com
    '''

    node = node_get(name=name)

    if 'Error' in node:
        return {'Error': 'Unable to retreive node'}

    if node[name]['path'] == '':
        file_path = os.path.join(_get_nodes_dir(), name + '.yml')
    else:
        file_path = os.path.join(_get_nodes_dir(), node[name]['path'], name + '.yml')

    os.remove(file_path)

    ret = 'Node {0} deleted'.format(name)

    return ret


def node_get(name, path=None, **kwargs):
    '''
    Return a specific node

    CLI Examples:

    .. code-block:: bash

        salt '*' reclass.node_get host01.domain.com
        salt '*' reclass.node_get name=host02.domain.com
    '''
    ret = {}
    nodes = node_list(**kwargs)

    if not name in nodes:
        return {'Error': 'Error in retrieving node'}
    ret[name] = nodes[name]
    return ret


def node_list(**connection_args):
    '''
    Return a list of available nodes

    CLI Example:

    .. code-block:: bash

        salt '*' reclass.node_list
    '''
    ret = {}

    for root, sub_folders, files in os.walk(_get_nodes_dir()):
        for fl in files:
            file_path = os.path.join(root, fl)
            with open(file_path, 'r') as file_handle:
                file_read = yaml.load(file_handle.read())
            file_data = file_read or {}
            classes = file_data.get('classes', [])
            parameters = file_data.get('parameters', {}).get('_param', [])
            name = fl.replace('.yml', '')
            host_name = name.split('.')[0]
            domain_name = '.'.join(name.split('.')[1:])
            path = root.replace(_get_nodes_dir()+'/', '')
            ret[name] = {
                'name': host_name,
                'domain': domain_name,
                'cluster': 'default',
                'environment': 'prd',
                'path': path,
                'classes': classes,
                'parameters': parameters
            }

    return ret


def node_update(name, classes=None, parameters=None, **connection_args):
    '''
    Update a node metadata information, classes and parameters.

    CLI Examples:

    .. code-block:: bash

        salt '*' reclass.node_update name=nodename classes="[clas1, class2]"
    '''
    node = node_get(name=name)
    if not node.has_key('Error'):
        node = node[name.split("/")[1]]
    else:
        return {'Error': 'Error in retrieving node'}


def _get_node_classes(node_data, class_mapping_fragment):
    classes = []

    for value_tmpl_string in class_mapping_fragment.get('value_template', []):
        value_tmpl = Template(value_tmpl_string.replace('<<', '${').replace('>>', '}'))
        rendered_value = value_tmpl.safe_substitute(node_data)
        classes.append(rendered_value)

    for value in class_mapping_fragment.get('value', []):
        classes.append(value)

    return classes


def _get_params(node_data, class_mapping_fragment):
    params = {}

    for param_name, param in class_mapping_fragment.items():
        value = param.get('value', None)
        value_tmpl_string = param.get('value_template', None)
        if value:
            params.update({param_name: value})
        elif value_tmpl_string:
            value_tmpl = Template(value_tmpl_string.replace('<<', '${').replace('>>', '}'))
            rendered_value = value_tmpl.safe_substitute(node_data)
            params.update({param_name: rendered_value})

    return params


def _validate_condition(node_data, expression_tmpl_string):
    expression_tmpl = Template(expression_tmpl_string.replace('<<', '${').replace('>>', '}'))
    expression = expression_tmpl.safe_substitute(node_data)

    if expression and expression == 'all':
        return True
    elif expression:
        val_a = expression.split('__')[0]
        val_b = expression.split('__')[2]
        condition = expression.split('__')[1]
        if condition == 'startswith':
            return val_a.startswith(val_b)
        elif condition == 'equals':
            return val_a == val_b

    return False


def node_classify(node_name, node_data={}, class_mapping={}, **kwargs):
    '''
    CLassify node by given class_mapping dictionary

    :param node_name: node FQDN
    :param node_data: dictionary of known informations about the node
    :param class_mapping: dictionary of classes and parameters, with conditions

    '''
    # clean node_data
    node_data = {k: v for (k, v) in node_data.items() if not k.startswith('__')}

    classes = []
    node_params = {}
    cluster_params = {}
    ret = {'node_create': '', 'cluster_param': {}}

    for type_name, node_type in class_mapping.items():
        valid = _validate_condition(node_data, node_type.get('expression', ''))
        if valid:
            gen_classes = _get_node_classes(node_data, node_type.get('node_class', {}))
            classes = classes + gen_classes
            gen_node_params = _get_params(node_data, node_type.get('node_param', {}))
            node_params.update(gen_node_params)
            gen_cluster_params = _get_params(node_data, node_type.get('cluster_param', {}))
            cluster_params.update(gen_cluster_params)

    if classes:
        create_kwargs = {'name': node_name, 'path': '_generated', 'classes': classes, 'parameters': node_params}
        ret['node_create'] = node_create(**create_kwargs)

    for name, value in cluster_params.items():
        ret['cluster_param'][name] = cluster_meta_set(name, value)

    return ret


def inventory(**connection_args):
    '''
    Get all nodes in inventory and their associated services/roles classification.

    CLI Examples:

    .. code-block:: bash

        salt '*' reclass.inventory
    '''
    defaults = find_and_read_configfile()
    storage = get_storage(defaults['storage_type'], _get_nodes_dir(), _get_classes_dir())
    reclass = Core(storage, None)
    nodes = reclass.inventory()["nodes"]
    output = {}

    for node in nodes:
        service_classification = []
        role_classification = []
        for service in nodes[node]['parameters']:
            if service not in ['_param', 'private_keys', 'public_keys', 'known_hosts']:
                service_classification.append(service)
                for role in nodes[node]['parameters'][service]:
                    if role not in ['_support', '_orchestrate', 'common']:
                        role_classification.append('%s.%s' % (service, role))
        output[node] = {
            'roles': role_classification,
            'services': service_classification,
        }
    return output


def cluster_meta_list(file_name="overrides.yml", cluster="", **kwargs):
    path = os.path.join(_get_cluster_dir(), cluster, file_name)
    try:
        with io.open(path, 'r') as file_handle:
            meta_yaml = yaml.safe_load(file_handle.read())
        meta = meta_yaml or {}
    except Exception as e:
        msg = "Unable to load cluster metadata YAML %s: %s" % (path, repr(e))
        LOG.debug(msg)
        meta = {'Error': msg}
    return meta


def cluster_meta_delete(name, file_name="overrides.yml", cluster="", **kwargs):
    ret = {}
    path = os.path.join(_get_cluster_dir(), cluster, file_name)
    meta = __salt__['reclass.cluster_meta_list'](path, **kwargs)
    if 'Error' not in meta:
        metadata = meta.get('parameters', {}).get('_param', {})
        if name not in metadata:
            return ret
        del metadata[name]
        try:
            with io.open(path, 'w') as file_handle:
                file_handle.write(unicode(yaml.dump(meta, default_flow_style=False)))
        except Exception as e:
            msg = "Unable to save cluster metadata YAML: %s" % repr(e)
            LOG.error(msg)
            return {'Error': msg}
        ret = 'Cluster metadata entry {0} deleted'.format(name)
    return ret


def cluster_meta_set(name, value, file_name="overrides.yml", cluster="", **kwargs):
    path = os.path.join(_get_cluster_dir(), cluster, file_name)
    meta = __salt__['reclass.cluster_meta_list'](path, **kwargs)
    if 'Error' not in meta:
        if not meta:
            meta = {'parameters': {'_param': {}}}
        metadata = meta.get('parameters', {}).get('_param', {})
        if name in metadata and metadata[name] == value:
            return {name: 'Cluster metadata entry %s already exists and is in correct state' % name}
        metadata.update({name: value})
        try:
            with io.open(path, 'w') as file_handle:
                file_handle.write(unicode(yaml.dump(meta, default_flow_style=False)))
        except Exception as e:
            msg = "Unable to save cluster metadata YAML %s: %s" % (path, repr(e))
            LOG.error(msg)
            return {'Error': msg}
        return cluster_meta_get(name, path, **kwargs)
    return meta


def cluster_meta_get(name, file_name="overrides.yml", cluster="", **kwargs):
    ret = {}
    path = os.path.join(_get_cluster_dir(), cluster, file_name)
    meta = __salt__['reclass.cluster_meta_list'](path, **kwargs)
    metadata = meta.get('parameters', {}).get('_param', {})
    if 'Error' in meta:
        ret['Error'] = meta['Error']
    elif name in metadata:
        ret[name] = metadata.get(name)

    return ret

