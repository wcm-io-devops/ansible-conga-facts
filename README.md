# conga-facts

This role supplies the configuration from the CONGA model as facts. It consists mainly of an action plugin which can be used independently from the role, but is packaged as a role so that other roles can declare it as dependency and have access to the CONGA facts.

To determine which CONGA role to use in a specific context, the plugin uses different strategies. Generally speaking, it tries to match the name of an Ansible role to the name of a CONGA role, so that it should be enough to name an Ansible role identical to a CONGA role to automatically match it. An optional `conga-` prefix is stripped from the Ansible role name before the comparison, so that you can prefix the CONGA specific roles to quickly identify them by name. Specifically, the lookup logic works like this:

* It checks whether the `conga_role_mapping` variable is set and use that role name if it is. This can be used to explicitly set a role mapping if you can't or don't want to use the name-based auto resolution, e.g. if a generic Ansible role should be mapped to a specific CONGA role (which is quite common).
* It checks whether the name of the current Ansible role matches a CONGA role name. This works if `conga_facts` is executed as a task in the context of a properly named role (i.e. the same as the associated CONGA role with an optional  `conga-` prefix).
* It checks whether the name of the top-level Ansible role in the dependency chain of the current role execution matches a CONGA role name. This works if `conga_facts` is executed as a (transitive) dependency of a properly named role. This allows you to simply declare this role as a dependency and have the CONGA variables resolved for your role.
* It checks whether the role of the top-level parent of the current task matches a CONGA role name. This works if `conga_facts` is executed via the `include_role` task, either directly or indirectly (as a dependency of another role). This allows you to reuse another generic role (like [`conga-files`](https://github.com/wcm-io-devops/ansible-conga-files)) in your role an have the CONGA variable resolved as expected.

> The plugin outputs the CONGA role and variants it resolved together with the resolution mechanism it used (`mapping`, `current`, `dependency` or `role`).

**tl;dr:** If you want to write a Ansible role that corresponds to a single, specific CONGA role, name it `conga-<rolename>`.  If you write (or use) a more generic Ansible role that can handle multiple, different CONGA roles, name it descriptively and set `conga_role_mapping`. The details of the resolution are basically internals you should need to care about.      

## Requirements

This role needs access to the `model.yml` files generated by CONGA. It tries to read the model files on `localhost` from the directory specified by the `conga_basedir` . For this to work, the CONGA configuration needs to be compiled before executing `conga-facts`. This can be achieved by either running the [`conga-maven`](https://github.com/wcm-io-devops/ansible-conga-maven) role beforehand or compiling the CONGA configuration by some other means and pointing the `conga_basedir` variable to it.
 > Please note that the configuration currently always has to be located on localhost (the machine Ansible is executed on) since action plugins always run locally (and only action plugins have sufficient access to the playbook structure for the plugin to do its magic).

The role also needs to know the current CONGA environment and the CONGA node the current host represents. This is achieved by setting the `conga_environment` and `conga_node` variables. The `conga_environment` variable would normally be set as a group variable for an inventory group that represents the environment while `conga_node` would be set in the inventory per host. Since `conga_node` defaults to the current inventory hostname it's also possible to name the CONGA nodes the same as in the Ansible inventory.
> If more than one CONGA node is represented by a single Ansible host this won't work and the node mapping needs to be explicitly set in the playbook. It is planned to simplify this by tighter integration of the CONGA environment and Ansible inventory.

## Role Variables

| Name              | Description          |
|-------------------|----------------------|
| `conga_environment` | Name of the CONGA environment to use. |
| `conga_node` | Name of the CONGA node to use for the current host. Defaults to the inventory hostname of the host the current task is running on. |
| `conga_basedir` | Base directory of the CONGA configuration. |
| `conga_model_file` | Name of the CONGA model file. Defaults to `model.yaml`. |
| `conga_target_path` | Relative path of the compiled CONGA configuration within `conga_basedir`. Defaults to `target/configuration`. |

## Facts

The following facts are supplied by the `conga_facts` role/plugin:

* `{{ conga_role }}`: Name of the current CONGA role
* `{{ conga_variant }}`: Name of the current CONGA variant
* `{{ conga_config }}`: The CONGA config parameters resolved for the current CONGA role/variant combination
* `{{ conga_config_path }}`: The base path of the files generated by CONGA for the current node.
* `{{ conga_tenants }}`: The CONGA tenants and their resolved config
* `{{ conga_files }}`: The list of config files generated by CONGA for the role/variant. The paths are relative to `conga_config_path`
* `{{ conga_packages }}`: The list of AEM packages generated by CONGA for the role/variant. The paths are relative to `conga_config_path`
* `{{ conga_directories }}`: A list of unique config directories generated by CONGA

## Example Playbook

This playbook compiles the [CONGA example configuration](https://github.com/wcm-io-devops/conga/tree/develop/example) and outputs the CONGA configuration variables for both the role `tomcat-services` and `tomcat-backendconnector` for node `services-1`:

    - hosts: localhost
      roles:
        - { role: conga-maven,
            conga_maven_git_repo: "https://github.com/wcm-io-devops/conga.git",
            conga_maven_git_branch: master,
            conga_maven_root: example }
    
    - hosts: services-1
      vars:
        conga_target_path: environments/target/configuration
      pre_tasks:
        # Used as a task (e.g. if you want to use CONGA facts in roles that should not depend on CONGA)
        - conga_facts:
            conga_role_mapping: tomcat-services
        - debug:
            msg: "{{ conga_config }}"
      roles:
        # Used a a role (but normally you would use it as a dependency to another role)
        - { role: conga-facts,
            conga_role_mapping: tomcat-backendconnector }
      tasks:
        - debug:
            msg: "{{ conga_config }}"