#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

import os
import re

from ansible.module_utils._text import to_native
from ansible.plugins.action import ActionBase
from ansible.errors import AnsibleOptionsError

try:
    from __main__ import display
except ImportError:
    from ansible.utils.display import Display
    display = Display()


class ActionModule(ActionBase):
    TRANSFERS_FILES = False

    def __init__(self, task, connection, play_context, loader, templar, shared_loader_obj):
        super(ActionModule, self).__init__(task, connection, play_context, loader, templar, shared_loader_obj)
        self._task_vars = None

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

            # Get CONGA basedir
            conga_basedir = self.conga_basedir

            # Get CONGA Maven target directory and build complete config path
            conga_target_path = self._get_arg_or_var('conga_target_path', 'target/configuration')
            conga_config_path = os.path.join(self.conga_basedir, conga_target_path, conga_environment, conga_node)

            # Get explicit role mapping
            conga_role_mapping = self._get_arg_or_var('conga_role_mapping', None, False)

            # Get explicit variant mapping
            conga_variant_mapping = self._get_arg_or_var('conga_variant_mapping', None, False)

            # Get name of model file, use model.yaml by default
            conga_model_file = self._get_arg_or_var('conga_model_file', 'model.yaml')
        except Exception as err:
            return self._fail_result(result, err.message)

        # Parse CONGA model YAML
        model_file = os.path.join(conga_config_path, conga_model_file)
        try:
            with open(model_file) as f:
                model = self._loader.load(f.read())
        except Exception as err:
            return self._fail_result(result, "could not parse model file '%s': %s" % (model_file, to_native(err)))

        roles = model.get("roles", [])

        model_role = None
        if conga_role_mapping:
            # Allow overriding the CONGA role with the conga_role_mapping variable or argument
            model_role = self._match_conga_role(roles, conga_role_mapping, conga_variant_mapping)
            role_source = 'mapping'
            # Fail if a mapping was provided but couldn't be matched. Otherwise we might yield an unexpected match that was clearly not intended.
            if not model_role:
                return self._fail_result(result, "unable to match CONGA role for explicit role mapping: '%s' and node '%s' " % (conga_role_mapping, conga_node))

        if not model_role:
            # Resolve the CONGA role via the name of the current Ansible role
            model_role = self._match_conga_role(roles, self.current_role, conga_variant_mapping)
            role_source = 'current'
        if not model_role:
            # Resolve the CONGA role via the name of the first Ansible role in the dependency chain
            model_role = self._match_conga_role(roles, self.depending_role, conga_variant_mapping)
            role_source = 'dependency'
        if not model_role:
            # Resolve the CONGA role via the top-level parent role of the task
            # This is necessary if a role is not executed as a dependency but via include_role
            model_role = self._match_conga_role(roles, self.parent_role, conga_variant_mapping)
            role_source = 'parent'
        if not model_role:
            # Fail the task if no CONGA role could be resolved
            return self._fail_result(result, ("unable to match CONGA role for node '%s' "
                                              "[role_mapping: '%s', "
                                              "variant_mapping: '%s', "
                                              "current: '%s', "
                                              "dependency: '%s', "
                                              "parent: '%s']") % (
                conga_node,
                conga_role_mapping,
                conga_variant_mapping,
                self.current_role,
                self.depending_role,
                self.parent_role))

        # Build result variables
        conga_role = model_role.get("role", None)
        conga_variant = model_role.get("variant", None)
        conga_variants = model_role.get("variants", [])
        conga_config = model_role.get("config", {})
        conga_tenants = model_role.get("tenants", {})
        conga_version_info = model.get("versionInfo", {})

        # Always display resolved role and mapping
        display.display(
            "[%s (%s)] (%s) => role: %s, variants: %s" %
            (task_vars['inventory_hostname'], conga_node, role_source, conga_role, conga_variants))

        # Build lists of CONGA files and packages
        conga_files_paths, conga_files, conga_bundle_files, conga_packages = self._get_files_and_packages(model_role)

        # Build unique list of directories from the list of files
        conga_directories = list(set([os.path.dirname(p) for p in conga_files_paths]))

        result["ansible_facts"] = {
            "conga_basedir": conga_basedir,
            "conga_role": conga_role,
            "conga_variant": conga_variant,
            "conga_variants": conga_variants,
            "conga_config_path": conga_config_path,
            "conga_config": conga_config,
            "conga_tenants": conga_tenants,
            "conga_files_paths": conga_files_paths,
            "conga_files": conga_files,
            "conga_bundle_files": conga_bundle_files,
            "conga_packages": conga_packages,
            "conga_directories": conga_directories,
            "conga_version_info": conga_version_info
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
    def conga_basedir(self):
        # Get CONGA basedir from the host vars of the host CONGA was executed on
        # Currently this has to be localhost, since we need access to the generated files

        # Check if conga_basedir was defined explicitly in play variables or via set_facts.
        conga_basedir = self._get_arg_or_var("conga_basedir", None, False)
        if conga_basedir:
            return conga_basedir

        conga_host = self._get_arg_or_var('conga_host', 'localhost')
        conga_basedir = self._task_vars['hostvars'].get(conga_host, {}).get('conga_basedir')
        if not conga_basedir:
            raise AnsibleOptionsError("parameter conga_basedir is required")
        else:
            return conga_basedir

    @property
    def parent_role(self):
        parent_role = None
        parent = self._task._parent
        while parent:
            if hasattr(parent, '_role') and hasattr(parent._role, '_role_name'):
                parent_role = parent._role._role_name
            parent = parent._parent
        return parent_role

    @property
    def current_role(self):
        if self._task._role:
            return self._task._role._role_name

    def _match_conga_role(self, roles, ansible_role, ansible_variant):
        if not ansible_role:
            return None

        # remove namespace and 'conga_' prefix before trying to match
        ansible_role = re.sub(r"^(.+\.)?(conga_)?", "", ansible_role)
        # replace "_" against "-" since ansible galaxy is exchanging "-" against "_"
        ansible_role = ansible_role.replace("_", "-")

        # filter by role name
        matching_roles = list(filter(lambda role: role.get("role", "") == ansible_role, roles))

        # filter matching roles by variant name
        if ansible_variant:
            matching_roles = list(filter(lambda role: ansible_variant in role.get("variants", ""), matching_roles))

        # warn if the matched role is not unique
        if len(matching_roles) > 1:
            if ansible_variant:
                display.warning("multiple roles in the CONGA model match role '%s' with variant '%s'" % (ansible_role, ansible_variant))
            else:
                display.warning("multiple roles in the CONGA model match role '%s' and no variant mapping was provided" % (ansible_role))
            display.warning("proceeding with first match.")

        # use first match
        return next(iter(matching_roles or []), None)

    def _get_files_and_packages(self, role):
        conga_files_paths = []
        conga_files = []
        conga_bundle_files = []
        conga_packages = []

        for role_file in role.get("files", []):
            path = role_file.get("path", None)
            if "aemContentPackageProperties" in role_file:
                # If the file has package properties we know it's an AEM package
                conga_packages.append(role_file)
            elif "bundleFileProperties" in role_file:
                # If the file has bundle file properties we know it belong to an AEM/sling bundle
                conga_bundle_files.append(role_file)
            else:
                # It's a regular file otherwise
                conga_files_paths.append(path)
                conga_files.append(role_file)

        return conga_files_paths, conga_files, conga_bundle_files, conga_packages

    def _get_arg_or_var(self, name, default=None, is_required=True):
        ret = self._task.args.get(name, self._task_vars.get(name, default))
        ret = self._templar.template(ret)
        if is_required and not ret:
            raise AnsibleOptionsError("parameter %s is required" % name)
        else:
            return ret
