from rally import consts
from rally.task import validation
from rally.plugins.openstack import scenario
from rally.plugins.openstack.scenarios.vrrp import utils as vrrp_utils
from rally.task import types
from task import atomic


class VRRPTasks(vrrp_utils.VRRPScenario):

    @types.set(image=types.ImageResourceType,
               flavor=types.FlavorResourceType)
    @validation.image_valid_on_flavor("flavor", "image")
    @validation.valid_command("command", required=False)
    @validation.external_network_exists("floating_network")
    @validation.required_services(consts.Service.NOVA, consts.Service.NEUTRON)
    @validation.required_openstack(users=True)
    @scenario.configure(context={"cleanup": ["nova", "neutron"],
                                 "keypair": {}, "allow_ssh": {}})
    def boot_failover_poll(self, image, flavor,
                           floating_network=None,
                           use_floating_ip=True,
                           # force_delete=False,
                           poll_duration=0,
                           poll_interval=0,
                           l3_nodes=None,
                           command=None,
                           **kwargs):
        """

        :param poll_duration: int. 0 will use defaults from conf
        :param poll_interval: int. 0 will use defaults from conf
        :param l3_nodes: dictionary with credentials to the different l3-nodes
            where the keys are the agent host-names from the Neutron DB

            Examples::

                l3_nodes: {
                  net1: {
                    address: 10.35.186.187
                    username: root
                    password: 123456,
                    port: 21
                  },
                  net2: {
                    address: net2.example.com
                    username: root
                    pkey: /path/to/ssh/id_rsa.pub
                  }
                }
        :param command: dict. Command that will be used to trigger failover
            will be executed via ssh on the node hosting the l3-agent. For more
            details see: VMTask.boot_runcommand_delete.command

        Note: failure injection usually requires root acess to the nodes,
            eithre via root user or by disabling 'Defaults requiretty' in
            /etc/sudoers
        """
        atomic_ping = self._wait_for_ping
        server, fip = self._boot_server_with_fip(
            image, flavor, use_floating_ip=use_floating_ip,
            floating_network=floating_network,
            key_name=self.context["user"]["keypair"]["name"],
            **kwargs)

        router_id = self.get_router(server, fip)

        with atomic.ActionTimer(self, "VRRP.get_master_agent.init"):
            master = self.get_master_agent(router_id)

        with atomic.ActionTimer(self, "VRRP.wait_for_ping.init_server"):
            self._wait_for_ping(fip["ip"])

        self.failover(host=l3_nodes[master["host"]],
                      command=command)
        # self.failover(host=l3_nodes[l3_nodes.keys()[0]],
        #               command=command)
        with atomic.ActionTimer(self, "VRRP.wait_for_ping.after_failover"):
            self._wait_for_ping(fip["ip"])
        with atomic.ActionTimer(self, "VRRP.get_master_agent.after_failover"):
            master_new = self.get_master_agent(router_id)

        msg = "router remains ACTIVE on the same node"
        assert master_new["id"] != master["id"], msg
