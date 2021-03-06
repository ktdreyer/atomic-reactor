"""
Copyright (c) 2015 Red Hat, Inc
All rights reserved.

This software may be modified and distributed under the terms
of the BSD license. See the LICENSE file for details.
"""

import os
import sys

from atomic_reactor.util import ImageName
from atomic_reactor.inner import PushConf

try:
    if sys.version_info.major > 2:
        # importing dockpulp in Python 3 causes SyntaxError
        raise ImportError

    import dockpulp
except ImportError:
    import inspect

    # Find our dockpulp stub
    import tests.mock.dockpulp as dockpulp
    mock_dockpulp_path = os.path.dirname(inspect.getfile(dockpulp.Pulp))
    if mock_dockpulp_path not in sys.path:
        sys.path.insert(0, os.path.dirname(mock_dockpulp_path))

    # Now load it properly, the same way the plugin will
    del dockpulp
    import dockpulp

from atomic_reactor.plugins.post_pulp_sync import PulpSyncPlugin, get_manifests_in_pulp_repository
from atomic_reactor.plugins.pre_reactor_config import (ReactorConfigPlugin,
                                                       WORKSPACE_CONF_KEY,
                                                       ReactorConfig)
from atomic_reactor.constants import PLUGIN_PULP_PUSH_KEY
from atomic_reactor.pulp_util import PulpLogWrapper

from flexmock import flexmock
import json
import pytest


class MockPulp(object):
    """
    Mock dockpulp.Pulp object
    """

    registry = 'pulp.example.com'

    def login(self, username, password):
        pass

    def set_certs(self, cer, key):
        pass

    def syncRepo(self, env=None, repo=None, config_file=None, prefix_with=None,
                 feed=None, basic_auth_username=None, basic_auth_password=None,
                 ssl_validation=None):
        pass

    def getRepos(self, rids, fields=None):
        pass

    def getPrefix(self):
        return 'redhat-'

    def createRepo(self, repo_id, url, registry_id=None, desc=None,
                   title=None, protected=False, distributors=True,
                   prefix_with='redhat-', productline=None):
        pass

    def crane(self, repos, wait=True):
        pass

    def listRepos(self, repos, content=False):
        return [{
            'id': repo,
            'manifests': {
                'sha256:{}'.format(repo): {
                    'layers': ['sha256:layer1', 'sha256:layer2'],
                    'tag': 'the-tag',
                }
            }} for repo in repos]


class TestPostPulpSync(object):
    @staticmethod
    def workflow(docker_repos, registry=None):
        images = []
        for tag in ['1.0-1', '1.0', 'latest', 'unique-timestamp']:
            images.extend([ImageName.parse(
                            '{0}/{1}:{2}'.format(registry, repo, tag).lstrip('/')
                          ) for repo in docker_repos])

        tag_conf = flexmock(images=images)
        push_conf = PushConf()
        return flexmock(tag_conf=tag_conf,
                        push_conf=push_conf,
                        postbuild_plugins_conf=[],
                        plugin_workspace={})

    @pytest.mark.parametrize('get_prefix', [True, False])
    @pytest.mark.parametrize(('pulp_repo_prefix', 'expected_prefix'), [
        (None, 'redhat-'),
        ('prefix-', 'prefix-')
    ])
    def test_pulp_repo_prefix(self,
                              get_prefix,
                              pulp_repo_prefix,
                              expected_prefix, reactor_config_map):
        docker_registry = 'http://registry.example.com'
        docker_repository = 'prod/myrepository'
        prefixed_pulp_repoid = '{}prod-myrepository'.format(expected_prefix)
        env = 'pulp'
        kwargs = {}
        if pulp_repo_prefix:
            kwargs['pulp_repo_prefix'] = pulp_repo_prefix

        if reactor_config_map:
            self.workflow.plugin_workspace = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key] = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key][WORKSPACE_CONF_KEY] =\
                ReactorConfig({'version': 1, 'pulp': {'name': env}})

        plugin = PulpSyncPlugin(tasker=None,
                                workflow=self.workflow([docker_repository]),
                                pulp_registry_name=env,
                                docker_registry=docker_registry,
                                **kwargs)

        mockpulp = MockPulp()
        if get_prefix:
            (flexmock(mockpulp)
                .should_receive('getPrefix')
                .with_args()
                .and_return(expected_prefix))
        else:
            (flexmock(mockpulp)
                .should_receive('getPrefix')
                .with_args()
                .and_raise(AttributeError))

        (flexmock(mockpulp)
            .should_receive('getRepos')
            .with_args([prefixed_pulp_repoid], fields=['id'])
            .and_return([{'id': prefixed_pulp_repoid}])
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('syncRepo')
            .with_args(repo=prefixed_pulp_repoid,
                       feed=docker_registry)
            .and_return(([], []))
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('crane')
            .with_args([prefixed_pulp_repoid], wait=True)
            .once()
            .ordered())
        (flexmock(dockpulp)
            .should_receive('Pulp')
            .with_args(env=env)
            .and_return(mockpulp))

        plugin.run()

    def test_auth_none(self, reactor_config_map):  # noqa
        docker_registry = 'http://registry.example.com'
        docker_repository = 'prod/myrepository'
        prefixed_pulp_repoid = 'redhat-prod-myrepository'
        env = 'pulp'

        if reactor_config_map:
            self.workflow.plugin_workspace = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key] = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key][WORKSPACE_CONF_KEY] =\
                ReactorConfig({'version': 1, 'pulp': {'name': env}})

        plugin = PulpSyncPlugin(tasker=None,
                                workflow=self.workflow([docker_repository]),
                                pulp_registry_name=env,
                                docker_registry=docker_registry)

        mockpulp = MockPulp()
        (flexmock(mockpulp)
            .should_receive('login')
            .never())
        (flexmock(mockpulp)
            .should_receive('set_certs')
            .never())
        (flexmock(mockpulp)
            .should_receive('getRepos')
            .with_args([prefixed_pulp_repoid], fields=['id'])
            .and_return([{'id': prefixed_pulp_repoid}])
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('syncRepo')
            .with_args(repo=prefixed_pulp_repoid,
                       feed=docker_registry)
            .and_return(([], []))
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('crane')
            .with_args([prefixed_pulp_repoid], wait=True)
            .once()
            .ordered())
        (flexmock(dockpulp)
            .should_receive('Pulp')
            .with_args(env=env)
            .and_return(mockpulp))

        plugin.run()

    @pytest.mark.parametrize('cer_exists', [True, False])
    @pytest.mark.parametrize('key_exists', [True, False])
    def test_pulp_auth(self, tmpdir, cer_exists, key_exists, reactor_config_map):
        pulp_secret_path = str(tmpdir)
        cer = pulp_secret_path + '/pulp.cer'
        key = pulp_secret_path + '/pulp.key'
        if cer_exists:
            open(cer, 'w').close()

        if key_exists:
            open(key, 'w').close()

        docker_registry = 'http://registry.example.com'
        docker_repository = 'prod/myrepository'
        prefixed_pulp_repoid = 'redhat-prod-myrepository'
        env = 'pulp'

        if reactor_config_map:
            self.workflow.plugin_workspace = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key] = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key][WORKSPACE_CONF_KEY] =\
                ReactorConfig({'version': 1, 'pulp': {'name': env}})

        plugin = PulpSyncPlugin(tasker=None,
                                workflow=self.workflow([docker_repository]),
                                pulp_registry_name=env,
                                docker_registry=docker_registry,
                                pulp_secret_path=pulp_secret_path)

        mockpulp = MockPulp()
        (flexmock(mockpulp)
            .should_receive('login')
            .never())
        if cer_exists and key_exists:
            (flexmock(mockpulp)
                .should_receive('set_certs')
                .with_args(cer, key)
                .once()
                .ordered())
            (flexmock(mockpulp)
                .should_receive('getRepos')
                .with_args([prefixed_pulp_repoid], fields=['id'])
                .and_return([{'id': prefixed_pulp_repoid}])
                .once()
                .ordered())
            (flexmock(mockpulp)
                .should_receive('syncRepo')
                .with_args(repo=prefixed_pulp_repoid,
                           feed=docker_registry)
                .and_return(([], []))
                .once()
                .ordered())
            (flexmock(mockpulp)
                .should_receive('crane')
                .with_args([prefixed_pulp_repoid], wait=True)
                .once()
                .ordered())
        else:
            (flexmock(mockpulp)
                .should_receive('set_certs')
                .never())
            (flexmock(mockpulp)
                .should_receive('syncRepo')
                .never())
            (flexmock(mockpulp)
                .should_receive('crane')
                .never())

        (flexmock(dockpulp)
            .should_receive('Pulp')
            .with_args(env=env)
            .and_return(mockpulp))

        if cer_exists and key_exists:
            plugin.run()
        else:
            with pytest.raises(RuntimeError):
                plugin.run()

    @pytest.mark.parametrize('content', [
        None,
        '{"invalid-json',
    ])
    def test_dockercfg_missing_or_invalid(self, tmpdir, content, reactor_config_map):
        env = 'pulp'

        if content is not None:
            registry_secret = os.path.join(str(tmpdir), '.dockercfg')
            with open(registry_secret, 'w') as fp:
                fp.write(content)

        if reactor_config_map:
            self.workflow.plugin_workspace = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key] = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key][WORKSPACE_CONF_KEY] =\
                ReactorConfig({'version': 1, 'pulp': {'name': env}})

        plugin = PulpSyncPlugin(tasker=None,
                                workflow=self.workflow(['repo']),
                                pulp_registry_name=env,
                                docker_registry='http://registry.example.com',
                                registry_secret_path=str(tmpdir))

        mockpulp = MockPulp()
        (flexmock(dockpulp)
            .should_receive('Pulp')
            .with_args(env=env)
            .and_return(mockpulp))

        with pytest.raises(RuntimeError):
            plugin.run()

    def test_dockercfg_registry_not_present(self, tmpdir, reactor_config_map):  # noqa
        docker_registry = 'http://registry.example.com'
        docker_repository = 'prod/myrepository'
        prefixed_pulp_repoid = 'redhat-prod-myrepository'
        env = 'pulp'

        registry_secret = os.path.join(str(tmpdir), '.dockercfg')
        dockercfg = {
            'other-registry.example.com': {
                'username': 'user',
                'password': 'pass',
                'email': 'user@example.com',
            },
        }

        with open(registry_secret, 'w') as fp:
            json.dump(dockercfg, fp)

        if reactor_config_map:
            self.workflow.plugin_workspace = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key] = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key][WORKSPACE_CONF_KEY] =\
                ReactorConfig({'version': 1, 'pulp': {'name': env}})

        plugin = PulpSyncPlugin(tasker=None,
                                workflow=self.workflow([docker_repository]),
                                pulp_registry_name=env,
                                docker_registry=docker_registry,
                                registry_secret_path=str(tmpdir))

        mockpulp = MockPulp()
        (flexmock(mockpulp)
            .should_receive('getRepos')
            .with_args([prefixed_pulp_repoid], fields=['id'])
            .and_return([{'id': prefixed_pulp_repoid}])
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('syncRepo')
            .with_args(repo=prefixed_pulp_repoid,
                       feed=docker_registry)
            .and_return(([], []))
            .once()
            .ordered())
        (flexmock(dockpulp)
            .should_receive('Pulp')
            .with_args(env=env)
            .and_return(mockpulp))

        plugin.run()

    @pytest.mark.parametrize('scheme', ['http', 'https'])
    def test_dockercfg(self, tmpdir, scheme, reactor_config_map):
        docker_registry = '{}://registry.example.com'.format(scheme)
        docker_repository = 'prod/myrepository'
        prefixed_pulp_repoid = 'redhat-prod-myrepository'
        user = 'user'
        pw = 'pass'
        env = 'pulp'

        registry_secret = os.path.join(str(tmpdir), '.dockercfg')
        dockercfg = {
            'registry.example.com': {
                'username': user,
                'password': pw,
                'email': 'user@example.com',
            },
        }

        with open(registry_secret, 'w') as fp:
            json.dump(dockercfg, fp)

        if reactor_config_map:
            self.workflow.plugin_workspace = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key] = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key][WORKSPACE_CONF_KEY] =\
                ReactorConfig({'version': 1, 'pulp': {'name': env}})

        plugin = PulpSyncPlugin(tasker=None,
                                workflow=self.workflow([docker_repository]),
                                pulp_registry_name=env,
                                docker_registry=docker_registry,
                                registry_secret_path=str(tmpdir))

        mockpulp = MockPulp()
        (flexmock(mockpulp)
            .should_receive('getRepos')
            .with_args([prefixed_pulp_repoid], fields=['id'])
            .and_return([{'id': prefixed_pulp_repoid}])
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('syncRepo')
            .with_args(repo=prefixed_pulp_repoid,
                       feed=docker_registry,
                       basic_auth_username=user,
                       basic_auth_password=pw)
            .and_return(([], []))
            .once()
            .ordered())
        (flexmock(dockpulp)
            .should_receive('Pulp')
            .with_args(env=env)
            .and_return(mockpulp))

        plugin.run()

    @pytest.mark.parametrize(('insecure_registry', 'ssl_validation'), [
        (None, None),
        (True, False),
        (False, True),
    ])
    def test_insecure_registry(self, insecure_registry, ssl_validation, reactor_config_map):
        docker_registry = 'http://registry.example.com'
        docker_repository = 'prod/myrepository'
        prefixed_pulp_repoid = 'redhat-prod-myrepository'
        env = 'pulp'

        if reactor_config_map:
            self.workflow.plugin_workspace = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key] = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key][WORKSPACE_CONF_KEY] =\
                ReactorConfig({'version': 1, 'pulp': {'name': env}})

        plugin = PulpSyncPlugin(tasker=None,
                                workflow=self.workflow([docker_repository]),
                                pulp_registry_name=env,
                                docker_registry=docker_registry,
                                insecure_registry=insecure_registry)

        mockpulp = MockPulp()
        (flexmock(mockpulp)
            .should_receive('getRepos')
            .with_args([prefixed_pulp_repoid], fields=['id'])
            .and_return([{'id': prefixed_pulp_repoid}])
            .once()
            .ordered())
        sync_exp = flexmock(mockpulp).should_receive('syncRepo')
        if ssl_validation is None:
            sync_exp = sync_exp.with_args(repo=prefixed_pulp_repoid,
                                          feed=docker_registry)
        else:
            sync_exp = sync_exp.with_args(repo=prefixed_pulp_repoid,
                                          feed=docker_registry,
                                          ssl_validation=ssl_validation)

        (sync_exp
            .and_return(([], []))
            .once()
            .ordered())
        (flexmock(dockpulp)
            .should_receive('Pulp')
            .with_args(env=env)
            .and_return(mockpulp))

        plugin.run()

    @pytest.mark.parametrize('fail', [False, True])
    def test_dockpulp_loglevel(self, fail, caplog, reactor_config_map):
        loglevel = 3

        mockpulp = MockPulp()
        (flexmock(mockpulp)
            .should_receive('getRepos')
            .with_args(['redhat-prod-myrepository'], fields=['id'])
            .and_return([{'id': 'redhat-prod-myrepository'}])
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('syncRepo')
            .and_return(([], [])))
        flexmock(dockpulp).should_receive('Pulp').and_return(mockpulp)
        logger = flexmock()
        expectation = (logger
                       .should_receive('setLevel')
                       .with_args(loglevel)
                       .once())

        if fail:
            expectation.and_raise(ValueError)

        flexmock(PulpLogWrapper).should_receive('get_pulp_logger').and_return(logger).once()

        if reactor_config_map:
            self.workflow.plugin_workspace = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key] = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key][WORKSPACE_CONF_KEY] =\
                ReactorConfig({'version': 1, 'pulp': {'name': 'pulp'}})

        plugin = PulpSyncPlugin(tasker=None,
                                workflow=self.workflow(['prod/myrepository']),
                                pulp_registry_name='pulp',
                                docker_registry='http://registry.example.com',
                                dockpulp_loglevel=loglevel)
        plugin.run()

        errors = [record.getMessage() for record in caplog.records
                  if record.levelname == 'ERROR']

        if fail:
            assert len(errors) >= 1
        else:
            assert not errors

    @pytest.mark.parametrize('already_exists', [False, True])
    def test_store_registry(self, already_exists, reactor_config_map):
        docker_registry = 'http://registry.example.com'
        docker_repository = 'prod/myrepository'
        prefixed_pulp_repoid = 'redhat-prod-myrepository'
        env = 'pulp'
        workflow = self.workflow([docker_repository])

        mockpulp = MockPulp()
        (flexmock(mockpulp)
            .should_receive('login')
            .never())
        (flexmock(mockpulp)
            .should_receive('set_certs')
            .never())
        (flexmock(mockpulp)
            .should_receive('getRepos')
            .with_args([prefixed_pulp_repoid], fields=['id'])
            .and_return([{'id': prefixed_pulp_repoid}])
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('syncRepo')
            .with_args(repo=prefixed_pulp_repoid,
                       feed=docker_registry)
            .and_return(([], []))
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('crane')
            .with_args([prefixed_pulp_repoid], wait=True)
            .once()
            .ordered())
        (flexmock(dockpulp)
            .should_receive('Pulp')
            .with_args(env=env)
            .and_return(mockpulp))

        if already_exists:
            workflow.push_conf.add_pulp_registry(env, mockpulp.registry,
                                                 server_side_sync=False)

        if reactor_config_map:
            workflow.plugin_workspace = {}
            workflow.plugin_workspace[ReactorConfigPlugin.key] = {}
            workflow.plugin_workspace[ReactorConfigPlugin.key][WORKSPACE_CONF_KEY] =\
                ReactorConfig({'version': 1,
                               'pulp': {'name': env,
                                        'auth': {'user': '', 'password': ''}}})

        plugin = PulpSyncPlugin(tasker=None,
                                workflow=workflow,
                                pulp_registry_name=env,
                                docker_registry=docker_registry)

        num_registries = len(workflow.push_conf.pulp_registries)
        assert num_registries == (1 if already_exists else 0)
        plugin.run()
        assert len(workflow.push_conf.pulp_registries) == 1

    def test_create_missing_repo(self, reactor_config_map):  # noqa
        docker_registry = 'http://registry.example.com'
        docker_repository = 'prod/myrepository'
        prefixed_pulp_repoid = 'redhat-prod-myrepository'
        env = 'pulp'

        if reactor_config_map:
            self.workflow.plugin_workspace = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key] = {}
            self.workflow.plugin_workspace[ReactorConfigPlugin.key][WORKSPACE_CONF_KEY] =\
                ReactorConfig({'version': 1, 'pulp': {'name': env}})

        plugin = PulpSyncPlugin(tasker=None,
                                workflow=self.workflow([docker_repository]),
                                pulp_registry_name=env,
                                docker_registry=docker_registry)

        mockpulp = MockPulp()
        (flexmock(mockpulp)
            .should_receive('getRepos')
            .with_args([prefixed_pulp_repoid], fields=['id'])
            .and_return([])
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('createRepo')
            .with_args(prefixed_pulp_repoid, None,
                       registry_id=docker_repository,
                       prefix_with='redhat-')
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('syncRepo')
            .with_args(repo=prefixed_pulp_repoid,
                       feed=docker_registry)
            .and_return(([], []))
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('crane')
            .with_args([prefixed_pulp_repoid], wait=True)
            .once()
            .ordered())
        (flexmock(dockpulp)
            .should_receive('Pulp')
            .with_args(env=env)
            .and_return(mockpulp))

        plugin.run()

    @pytest.mark.parametrize('publish,has_pulp_push,should_publish', [
        (None, False, True),
        (None, True, False),
        (True, False, True),
        (True, True, False),
        (False, False, False),
        (False, True, False),
    ])
    def test_publish(self, publish, has_pulp_push, should_publish, caplog, reactor_config_map):
        docker_registry = 'http://registry.example.com'
        docker_repository = 'prod/myrepository'
        prefixed_pulp_repoid = 'redhat-prod-myrepository'
        env = 'pulp'

        mockpulp = MockPulp()
        (flexmock(mockpulp)
            .should_receive('login')
            .never())
        (flexmock(mockpulp)
            .should_receive('set_certs')
            .never())
        (flexmock(mockpulp)
            .should_receive('getRepos')
            .with_args([prefixed_pulp_repoid], fields=['id'])
            .and_return([{'id': prefixed_pulp_repoid}])
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('syncRepo')
            .with_args(repo=prefixed_pulp_repoid,
                       feed=docker_registry)
            .and_return(([], []))
            .once()
            .ordered())
        if should_publish:
            (flexmock(mockpulp)
                .should_receive('crane')
                .with_args([prefixed_pulp_repoid], wait=True)
                .once()
                .ordered())
        else:
            (flexmock(mockpulp)
                .should_receive('crane')
                .never())

        (flexmock(dockpulp)
            .should_receive('Pulp')
            .with_args(env=env)
            .and_return(mockpulp))

        workflow = self.workflow([docker_repository], mockpulp.registry)
        workflow.postbuild_plugins_conf.append(
            {
                'name': PulpSyncPlugin.key,
            },
        )
        if has_pulp_push:
            workflow.postbuild_plugins_conf.append(
                {
                    'name': PLUGIN_PULP_PUSH_KEY,
                },
            )

        kwargs = {
            'pulp_registry_name': env,
            'docker_registry': docker_registry,
        }
        if publish is not None:
            kwargs['publish'] = publish

        if reactor_config_map:
            workflow.plugin_workspace = {}
            workflow.plugin_workspace[ReactorConfigPlugin.key] = {}
            workflow.plugin_workspace[ReactorConfigPlugin.key][WORKSPACE_CONF_KEY] =\
                ReactorConfig({'version': 1,
                               'pulp': {'name': env,
                                        'auth': {'user': '', 'password': ''}}})

        plugin = PulpSyncPlugin(tasker=None,
                                workflow=workflow,
                                **kwargs)
        plugin.run()
        log_messages = [l.getMessage() for l in caplog.records]

        for image in workflow.tag_conf.images:
            expected_log = 'image available at %s' % image.to_str()
            if should_publish:
                assert expected_log in log_messages
            else:
                assert expected_log not in log_messages

    def test_workspace_updated(self, reactor_config_map):  # noqa
        docker_registry = 'http://registry.example.com'
        docker_repository = 'prod/myrepository'
        prefixed_pulp_repoid = 'redhat-prod-myrepository'
        env = 'pulp'

        mockpulp = MockPulp()
        (flexmock(mockpulp)
            .should_receive('getRepos')
            .with_args([prefixed_pulp_repoid], fields=['id'])
            .and_return([{'id': prefixed_pulp_repoid}])
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('syncRepo')
            .with_args(repo=prefixed_pulp_repoid,
                       feed=docker_registry)
            .and_return(([], []))
            .once()
            .ordered())
        (flexmock(mockpulp)
            .should_receive('crane')
            .with_args([prefixed_pulp_repoid], wait=True)
            .once()
            .ordered())

        (flexmock(dockpulp)
            .should_receive('Pulp')
            .with_args(env=env)
            .and_return(mockpulp))

        workflow = self.workflow([docker_repository], mockpulp.registry)
        workflow.postbuild_plugins_conf.append(
            {
                'name': PulpSyncPlugin.key,
            },
        )

        kwargs = {
            'pulp_registry_name': env,
            'docker_registry': docker_registry,
        }

        if reactor_config_map:
            workflow.plugin_workspace = {}
            workflow.plugin_workspace[ReactorConfigPlugin.key] = {}
            workflow.plugin_workspace[ReactorConfigPlugin.key][WORKSPACE_CONF_KEY] =\
                ReactorConfig({'version': 1,
                               'pulp': {'name': env,
                                        'auth': {'user': '', 'password': ''}}})

        plugin = PulpSyncPlugin(tasker=None,
                                workflow=workflow,
                                **kwargs)
        plugin.run()

        manifests = get_manifests_in_pulp_repository(workflow)
        assert manifests == ['sha256:{}'.format(prefixed_pulp_repoid)]
