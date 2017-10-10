#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import yaml
import os
import re

from ansible.module_utils._text import to_native
from ansible.plugins.action import ActionBase
from ansible.errors import AnsibleError, AnsibleOptionsError

class ActionModule(ActionBase):

    TRANSFERS_FILES = False

    def run(self, tmp=None, task_vars=None):
        if task_vars is None:
            task_vars = dict()

        result = super(ActionModule, self).run(tmp, task_vars)
        self._task_vars = task_vars

        try:
            # Get CONGA environment
            conga_environment = self._get_arg_or_var('conga_environment')

            # Get CONGA node name from conga_node, fallback to inventory_hostname if not defined
            conga_node = self._get_arg_or_var('conga_node', task_vars['inventory_hostname'])

            # Get CONGA basedir from the host vars of the host CONGA was executed on
            # Currently this has to be localhost, since we need access to the generated files
            conga_host = self._get_arg_or_var('conga_host', 'localhost')
            conga_basedir = task_vars['hostvars'].get(conga_host).get('conga_basedir')

            # Get CONGA Maven target directory and build complete config path
            conga_target_path = self._get_arg_or_var('conga_target_path', 'target/configuration')
            conga_config_path = os.path.join(conga_basedir, conga_target_path, conga_environment, conga_node)

            # Get explicit role mapping
            conga_role_mapping = self._get_arg_or_var('conga_role_mapping', None, False)

            # Get name of model file, use model.yaml by default
            conga_model_file = self._get_arg_or_var('conga_model_file', 'model.yaml')
        except AnsibleOptionsError as err:
            return self._fail_result(result, err.message)

        try:
            # Parse CONGA model YAML
            model_file = os.path.join(conga_config_path, conga_model_file)
            with open(model_file) as f:
                model = yaml.safe_load(f.read())
        except Exception as err:
            return self._fail_result(result, "could not parse model file '%s': %s" % (model_file, to_native(err)))

        roles = model.get("roles", [])

        # Allow overriding the CONGA role with the conga_role_mapping variable or argument
        conga_role = self._match_conga_role(roles, conga_role_mapping)
        role_source = 'mapping'
        if not conga_role:
            # Resolve the CONGA role via the name of the current Ansible role
            conga_role = self._match_conga_role(roles, self.current_role)
            role_source = 'current'
        if not conga_role:
            # Resolve the CONGA role via the name of the first Ansible role in the dependency chain
            conga_role = self._match_conga_role(roles, self.depending_role)
            role_source = 'dependency'
        if not conga_role:
            # Resolve the CONGA role via the top-level parent role of the task
            # This is necessary if a role is not executed as a dependency but via include_role
            conga_role = self._match_conga_role(roles, self.parent_role)
            role_source = 'parent'
        if not conga_role:
            # Fail the task if no CONGA role could be resolved
            return self._fail_result(result, "unable to match CONGA role for node '%s' [mapping: '%s', current: '%s', dependency: '%s', parent: '%s']" % (
                                     conga_node,
                                     conga_role_mapping,
                                     self.current_role,
                                     self.depending_role,
                                     self.parent_role))

        # Get role from model
        model_role = next((role for role in roles if role["role"] == conga_role), {})

        # Build result variables
        conga_role = model_role.get("role", None)
        conga_variant = model_role.get("variant", None)
        conga_config = model_role.get("config", {})
        conga_tenants = model_role.get("tenants", {})

        # Always display resolved role and mapping
        self._display.display(
            "[%s (%s)] (%s) => role: %s, variant: %s" %
            (task_vars['inventory_hostname'], conga_node, role_source, conga_role, conga_variant))

        # Build lists of CONGA files and packages
        conga_files_paths, conga_files, conga_packages = self._get_files_and_packages(model_role)

        # Build unique list of directories from the list of files
        conga_directories = list(set([os.path.dirname(f) for f in conga_files_paths]))

        result["ansible_facts"] = {
            "conga_basedir": conga_basedir,
            "conga_role": conga_role,
            "conga_variant": conga_variant,
            "conga_config_path": conga_config_path,
            "conga_config": conga_config,
            "conga_tenants": conga_tenants,
            "conga_files_paths": conga_files_paths,
            "conga_files": conga_files,
            "conga_packages": conga_packages,
            "conga_directories": conga_directories
        }

        return result

    @staticmethod
    def _fail_result(result, message):
        result['failed'] = True
        result['msg'] = message
        return result

    @property
    def depending_role(self):
        dep_chain = self._task.get_dep_chain()
        if dep_chain:
            return str(next(iter(dep_chain), None))

    @property
    def parent_role(self):
        parent = self._task._parent
        while parent:
            if hasattr(parent, '_role'):
                parent_role = parent._role._role_name
            parent = parent._parent
        return parent_role

    @property
    def current_role(self):
        if self._task._role:
            return self._task._role._role_name

    def _match_conga_role(self, roles, ansible_role):
        if not ansible_role:
            return None
        # Strip "conga-" prefix from Ansible role name
        ansible_role = re.sub("^conga-", "", ansible_role)
        # Iterate over CONGA roles and return the first match
        for role in roles:
            conga_role = role.get("role", "")
            if conga_role == ansible_role:
                return conga_role

    def _get_files_and_packages(self, role):
        conga_files_paths = []
        conga_files = []
        conga_packages = []

        for file in role.get("files", []):
            path = file.get("path", None)
            if "aemContentPackageProperties" in file:
                # If the file has package properties we know it's an AEM package
                conga_packages.append(file)
            else:
                # It's a regular file otherwise
                conga_files_paths.append(path)
                conga_files.append(file)

        return conga_files_paths, conga_files, conga_packages

    def _get_arg_or_var(self, name, default=None, is_required=True):
        ret = self._task.args.get(name, self._task_vars.get(name, default))
        if is_required and not ret:
            raise AnsibleOptionsError("parameter %s is required" % name)
        else:
            return ret

