from monster import util


class Upgrade(object):
    """
    Base upgrade class
    """

    def __init__(self, deployment):
        self.deployment = deployment

    def upgrade(self, rc=False):
        raise NotImplementedError

    def mungerate(self):
        """
        Prepares a 4.1.x -> 4.2.x upgrade with mungerator
        """
        chef_server = next(self.deployment.search_role('chefserver'))
        controllers = list(self.deployment.search_role('controller'))
        computes = list(self.deployment.search_role('compute'))
        controller1 = controllers[0]

        # purge cookbooks
        munge = ["for i in /var/chef/cache/cookbooks/*; do rm -rf $i; done"]
        ncmds = []
        ccmds = []
        controller1.add_run_list_item(['role[heat-all]'])

        if self.deployment.feature_in('highavailability'):
            controller2 = controllers[1]
            controller2.add_run_list_item(['role[heat-api]',
                                           'role[heat-api-cfn]',
                                           'role[heat-api-cloudwatch]'])

        if self.deployment.os_name == "precise":
            # For Ceilometer
            ncmds.extend([
                "apt-get clean",
                "apt-get -y install python-warlock python-novaclient babel"])
            # For Horizon
            ccmds.append(
                "apt-get -y install openstack-dashboard python-django-horizon")
            # For mungerator
            munge.extend(["apt-get -y install python-dev",
                          "apt-get -y install python-setuptools"])
            # For QEMU
            provisioner = str(self.deployment.provisioner)

            if provisioner == "rackspace" or provisioner == "openstack":
                ncmds.extend(
                    ["apt-get update",
                     "apt-get remove qemu-utils -y",
                     "apt-get install qemu-utils -y"])

        if self.deployment.os_name == "centos":
            # For mungerator
            munge.extend(["yum install -y openssl-devel",
                          "yum install -y python-devel",
                          "yum install -y python-setuptools"])

        node_commands = "; ".join(ncmds)
        controller_commands = "; ".join(ccmds)

        for controller in controllers:
            controller.run_cmd(node_commands)
            controller.run_cmd(controller_commands)

        for compute in computes:
            compute.run_cmd(node_commands)

        # backup db
        backup = util.config['upgrade']['commands']['backup-db']
        controller1.run_cmd(backup)

        # Munge away quantum
        munge_dir = "/opt/upgrade/mungerator"
        munge_repo = "https://github.com/rcbops/mungerator"
        munge.extend([
            "rm -rf {0}".format(munge_dir),
            "git clone {0} {1}".format(munge_repo, munge_dir),
            "cd {0}; python setup.py install".format(munge_dir),
            "mungerator munger --client-key /etc/chef-server/admin.pem "
            "--auth-url https://127.0.0.1:443 all-nodes-in-env "
            "--name {0}".format(self.deployment.name)])
        chef_server.run_cmd("; ".join(munge))
        self.deployment.environment.save_locally()
