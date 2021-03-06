from time import sleep
from provisioner import Provisioner
from chef import Node, Client, Search, autoconfigure

from monster import util
from monster.razor_api import razor_api


class Razor(Provisioner):
    """
    Provisions chef nodes in a Razor environment
    """

    def __init__(self, ip=None):
        self.ipaddress = ip or util.config['secrets']['razor']['ip']
        self.api = razor_api(self.ipaddress)

    def provision(self, template, deployment):
        """
        Provisions a ChefNode using Razor environment
        :param template: template for cluster
        :type template: dict
        :param deployment: ChefDeployment to provision for
        :type deployment: ChefDeployment
        :rtype: list
        """
        util.logger.info("Provisioning with Razor!")
        image = deployment.os_name
        return [self.available_node(image, deployment)
                for _ in template['nodes']]

    def available_node(self, image, deployment):
        """
        Provides a free node from chef pool
        :param image: name of os image
        :type image: string
        :param deployment: ChefDeployment to add node to
        :type deployment: ChefDeployment
        :rtype: ChefNode
        """
        # TODO: Should probably search on system name node attributes
        # Avoid specific naming of razor nodes, not portable
        nodes = self.node_search("name:qa-%s-pool*" % image)
        for node in nodes:
            is_default = node.chef_environment == "_default"
            iface_in_run_list = "recipe[network-interfaces]" in node.run_list
            if (is_default and iface_in_run_list):
                node.chef_environment = deployment.environment.name
                node['in_use'] = "provisioning"
                node.save()
                return node
        deployment.destroy()
        raise Exception("No more nodes!!")

    def destroy_node(self, node):
        """
        Destroys a node provisioned by razor
        :param node: Node to destroy
        :type node: ChefNode
        """
        cnode = Node(node.name, node.environment.local_api)
        in_use = node['in_use']
        if in_use == "provisioning" or in_use == 0:
            # Return to pool if the node is clean
            cnode['in_use'] = 0
            cnode['archive'] = {}
            cnode.chef_environment = "_default"
            cnode.save()
        else:
            # Remove active model if the node is dirty
            active_model = cnode['razor_metadata']['razor_active_model_uuid']
            try:
                if node.feature_in('controller'):
                    # rabbit can cause the node to not actually reboot
                    kill = ("for i in `ps -U rabbitmq | tail -n +2 | "
                            "awk '{print $1}' `; do kill -9 $i; done")
                    node.run_cmd(kill)
                node.run_cmd("shutdown -r now")
                self.api.remove_active_model(active_model)
                Client(node.name).delete()
                cnode.delete()
                sleep(15)
            except:
                util.logger.error("Node unreachable. "
                                  "Manual restart required:{0}".
                                  format(str(node)))

    @classmethod
    def node_search(cls, query, environment=None, tries=10):
        """
        Performs a node search query on the chef server
        :param query: search query to request
        :type query: string
        :param environment: Environment the query should be
        :type environment: ChefEnvironment
        :rtype: Iterator (chef.Node)
        """
        api = autoconfigure()
        if environment:
            api = environment.local_api
        search = None
        while not search and tries > 0:
            search = Search("node", api=api).query(query)
            sleep(10)
            tries = tries - 1
        return (n.object for n in search)
