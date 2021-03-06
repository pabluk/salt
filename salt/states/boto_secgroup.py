# -*- coding: utf-8 -*-
'''
Manage Security Groups
======================

.. versionadded:: 2014.7.0

Create and destroy Security Groups. Be aware that this interacts with Amazon's
services, and so may incur charges.

This module uses ``boto``, which can be installed via package, or pip.

This module accepts explicit EC2 credentials but can also utilize
IAM roles assigned to the instance through Instance Profiles. Dynamic
credentials are then automatically obtained from AWS API and no further
configuration is necessary. More information available `here
<http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html>`_.

If IAM roles are not used you need to specify them either in a pillar file or
in the minion's config file:

.. code-block:: yaml

    secgroup.keyid: GKTADJGHEIQSXMKKRBJ08H
    secgroup.key: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs

It's also possible to specify ``key``, ``keyid`` and ``region`` via a profile, either
passed in as a dict, or as a string to pull from pillars or minion config:

.. code-block:: yaml

    myprofile:
        keyid: GKTADJGHEIQSXMKKRBJ08H
        key: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs
        region: us-east-1

.. code-block:: yaml

    Ensure mysecgroup exists:
        boto_secgroup.present:
            - name: mysecgroup
            - description: My security group
            - rules:
                - ip_protocol: tcp
                  from_port: 80
                  to_port: 80
                  cidr_ip:
                    - 10.0.0.0/0
                    - 192.168.0.0/0
            - region: us-east-1
            - keyid: GKTADJGHEIQSXMKKRBJ08H
            - key: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs

    # Using a profile from pillars
    Ensure mysecgroup exists:
        boto_secgroup.present:
            - name: mysecgroup
            - description: My security group
            - region: us-east-1
            - profile: myprofile

    # Passing in a profile
    Ensure mysecgroup exists:
        boto_secgroup.present:
            - name: mysecgroup
            - description: My security group
            - region: us-east-1
            - profile:
                keyid: GKTADJGHEIQSXMKKRBJ08H
                key: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs
'''

# Import Python libs
import logging

# Import salt libs
import salt.utils.dictupdate as dictupdate
from salt.exceptions import SaltInvocationError

log = logging.getLogger(__name__)


def __virtual__():
    '''
    Only load if boto is available.
    '''
    return 'boto_secgroup' if 'boto_secgroup.exists' in __salt__ else False


def present(
        name,
        description,
        vpc_id=None,
        rules=None,
        region=None,
        key=None,
        keyid=None,
        profile=None):
    '''
    Ensure the security group exists with the specified rules.

    name
        Name of the security group.

    description
        A description of this security group.

    vpc_id
        The ID of the VPC to create the security group in, if any.

    rules
        A list of ingress rule dicts.

    region
        Region to connect to.

    key
        Secret key to be used.

    keyid
        Access key to be used.

    profile
        A dict with region, key and keyid, or a pillar key (string)
        that contains a dict with region, key and keyid.
    '''
    ret = {'name': name, 'result': None, 'comment': '', 'changes': {}}
    _ret = _security_group_present(name, description, vpc_id, region, key,
                                   keyid, profile)
    ret['changes'] = _ret['changes']
    ret['comment'] = ' '.join([ret['comment'], _ret['comment']])
    if _ret['result'] is not None:
        ret['result'] = _ret['result']
        if ret['result'] is False:
            return ret
    if not rules:
        rules = []
    _ret = _rules_present(name, rules, vpc_id, region, key, keyid, profile)
    ret['changes'] = dictupdate.update(ret['changes'], _ret['changes'])
    ret['comment'] = ' '.join([ret['comment'], _ret['comment']])
    if _ret['result'] is not None:
        ret['result'] = _ret['result']
    return ret


def _security_group_present(
        name,
        description,
        vpc_id,
        region,
        key,
        keyid,
        profile):
    '''
    given a group name or a group name and vpc id:
    1. determine if the group exists
    2. if the group does not exist, creates the group
    3. return the group's configuration and any changes made
    '''
    ret = {'result': None, 'comment': '', 'changes': {}}
    exists = __salt__['boto_secgroup.exists'](name, region, key, keyid,
                                              profile, vpc_id)
    if not exists:
        if __opts__['test']:
            msg = 'Security group {0} is set to be created.'.format(name)
            ret['comment'] = msg
            return ret
        created = __salt__['boto_secgroup.create'](name, description, vpc_id,
                                                   region, key, keyid, profile)
        if created:
            ret['result'] = True
            ret['changes']['old'] = {'secgroup': None}
            sg = __salt__['boto_secgroup.get_config'](name, None, region, key,
                                                      keyid, profile, vpc_id)
            ret['changes']['new'] = {'secgroup': sg}
            ret['comment'] = 'Security group {0} created.'.format(name)
        else:
            ret['result'] = False
            msg = 'Failed to create {0} security group.'.format(name)
            ret['comment'] = msg
    else:
        ret['comment'] = 'Security group {0} present.'.format(name)
    return ret


def _get_rule_changes(rules, _rules):
    '''
    given a list of desired rules (rules) and existing rules (_rules) return
    a list of rules to delete (to_delete) and to create (to_create)
    '''
    to_delete = []
    to_create = []
    # for each rule in state file
    # 1. validate rule
    # 2. determine if rule exists in existing security group rules
    for rule in rules:
        try:
            ip_protocol = rule.get('ip_protocol')
            to_port = rule.get('to_port')
            from_port = rule.get('from_port')
        except KeyError:
            raise SaltInvocationError('ip_protocol, to_port, and from_port are'
                                      ' required arguments for security group'
                                      ' rules.')
        supported_protocols = ['tcp', 'udp', 'icmp', 'all']
        if ip_protocol not in supported_protocols:
            msg = ('Invalid ip_protocol {0} specified in security group rule.')
            raise SaltInvocationError(msg.format(ip_protocol))
        cidr_ip = rule.get('cidr_ip', None)
        group_name = rule.get('source_group_name', None)
        group_id = rule.get('source_group_group_id', None)
        owner_id = rule.get('source_group_owner_id', None)
        if cidr_ip and (group_id or group_name):
            raise SaltInvocationError('cidr_ip and source groups can not both'
                                      ' be specified in security group rules.')
        if group_id and group_name:
            raise SaltInvocationError('Either source_group_group_id or'
                                      ' source_group_name can be specified in'
                                      ' security group rules, but not both.')
        if not (cidr_ip or group_id or group_name):
            raise SaltInvocationError('cidr_ip, source_group_group_id, or'
                                      ' source_group_name must be provided for'
                                      ' security group rules.')
        rule_found = False
        # for each rule in existing security group ruleset determine if
        # new rule exists
        for _rule in _rules:
            if (ip_protocol == _rule['ip_protocol'] and
                    from_port == _rule['from_port'] and
                    to_port == _rule['to_port']):
                _cidr_ip = _rule.get('cidr_ip', None)
                _owner_id = _rule.get('source_group_owner_id', None)
                _group_id = _rule.get('source_group_group_id', None)
                _group_name = _rule.get('source_group_name', None)
                if (cidr_ip == _cidr_ip or owner_id == _owner_id or
                        group_id == _group_id or group_name == _group_name):
                    rule_found = True
        if not rule_found:
            to_create.append(rule)
    # for each rule in existing security group configuration
    # 1. determine if rules needed to be deleted
    for _rule in _rules:
        _ip_protocol = _rule.get('ip_protocol')
        _to_port = _rule.get('to_port')
        _from_port = _rule.get('from_port')
        _cidr_ip = _rule.get('cidr_ip', None)
        _owner_id = _rule.get('source_group_owner_id', None)
        _group_id = _rule.get('source_group_group_id', None)
        _group_name = _rule.get('source_group_name', None)
        rule_found = False
        for rule in rules:
            cidr_ip = rule.get('cidr_ip', None)
            group_name = rule.get('source_group_name', None)
            group_id = rule.get('source_group_group_id', None)
            owner_id = rule.get('source_group_owner_id', None)
            if (rule['ip_protocol'] == _ip_protocol and
                    rule['from_port'] == _from_port and
                    rule['to_port'] == _to_port):
                if (cidr_ip == _cidr_ip or owner_id == _owner_id or
                        group_id == _group_id or group_name == _group_name):
                    rule_found = True
        if not rule_found:
            # Can only supply name or id, not both. Since we're deleting
            # entries, it doesn't matter which we pick.
            _rule.pop('source_group_name', None)
            to_delete.append(_rule)

    return (to_delete, to_create)


def _rules_present(
        name,
        rules,
        vpc_id,
        region,
        key,
        keyid,
        profile):
    '''
    given a group name or group name and vpc_id:
    1. get lists of desired rule changes (using _get_rule_changes)
    2. delete/revoke or authorize/create rules
    3. return 'old' and 'new' group rules
    '''
    ret = {'result': None, 'comment': '', 'changes': {}}
    sg = __salt__['boto_secgroup.get_config'](name, None, region, key, keyid,
                                              profile, vpc_id)
    if not sg:
        msg = '{0} security group configuration could not be retrieved.'
        ret['comment'] = msg.format(name)
        ret['result'] = False
        return ret
    # rules = rules that exist in salt state
    # sg['rules'] = that exist in present group
    to_delete, to_create = _get_rule_changes(rules, sg['rules'])
    if to_create or to_delete:
        if __opts__['test']:
            msg = 'Security group {0} set to have rules modified.'.format(name)
            ret['comment'] = msg
            return ret
        if to_delete:
            deleted = True
            for rule in to_delete:
                _deleted = __salt__['boto_secgroup.revoke'](
                    name, vpc_id=vpc_id, region=region, key=key, keyid=keyid,
                    profile=profile, **rule)
                if not _deleted:
                    deleted = False
            if deleted:
                msg = 'Removed rules on {0} security group.'.format(name)
                ret['comment'] = msg
                ret['result'] = True
            else:
                msg = 'Failed to remove rules on {0} security group.'
                ret['comment'] = msg.format(name)
                ret['result'] = False
        if to_create:
            created = True
            for rule in to_create:
                _created = __salt__['boto_secgroup.authorize'](
                    name, vpc_id=vpc_id, region=region, key=key, keyid=keyid,
                    profile=profile, **rule)
                if not _created:
                    created = False
            if created:
                msg = 'Created rules on {0} security group.'
                ret['comment'] = ' '.join([ret['comment'], msg.format(name)])
                if ret['result'] is not False:
                    ret['result'] = True
            else:
                msg = 'Failed to create rules on {0} security group.'
                ret['comment'] = ' '.join([ret['comment'], msg.format(name)])
                ret['result'] = False
        ret['changes']['old'] = {'rules': sg['rules']}
        sg = __salt__['boto_secgroup.get_config'](name, None, region, key,
                                                  keyid, profile, vpc_id)
        ret['changes']['new'] = {'rules': sg['rules']}
    return ret


def absent(
        name,
        vpc_id=None,
        region=None,
        key=None,
        keyid=None,
        profile=None):
    '''
    Ensure a security group with the specified name does not exist.

    name
        Name of the security group.

    vpc_id
        The ID of the VPC to create the security group in, if any.

    region
        Region to connect to.

    key
        Secret key to be used.

    keyid
        Access key to be used.

    profile
        A dict with region, key and keyid, or a pillar key (string)
        that contains a dict with region, key and keyid.
    '''
    ret = {'name': name, 'result': None, 'comment': '', 'changes': {}}

    sg = __salt__['boto_secgroup.get_config'](name, None, region, key, keyid,
                                              profile, vpc_id)
    if sg:
        if __opts__['test']:
            ret['result'] = None
            msg = 'Security group {0} is set to be removed.'.format(name)
            ret['comment'] = msg
            return ret
        deleted = __salt__['boto_secgroup.delete'](name, None, region, key,
                                                   keyid, profile, vpc_id)
        if deleted:
            ret['result'] = True
            ret['changes']['old'] = {'secgroup': sg}
            ret['changes']['new'] = {'secgroup': None}
            ret['comment'] = 'Security group {0} deleted.'.format(name)
        else:
            ret['result'] = False
            msg = 'Failed to delete {0} security group.'.format(name)
            ret['comment'] = msg
    else:
        ret['comment'] = '{0} security group does not exist.'.format(name)
    return ret
