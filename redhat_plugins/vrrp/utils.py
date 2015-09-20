import netaddr

from common import sshutils
from rally import exceptions
from rally.plugins.openstack.scenarios.vm import utils as vmutils
from rally.common import log as logging
from task import utils

LOG = logging.getLogger(__name__)



class VRRPScenario(vmutils.VMScenario):

    def get_master_agent(self, router_id):
        net_admin = self._admin_clients.neutron()

        def get_actives(r):
            agents = net_admin.list_l3_agent_hosting_routers(r)
            active_agents = filter(
                lambda d: d.get("ha_state") == "active",
                agents.get("agents", []))
            LOG.info("Router %s is ACTIVE on: %s" % (r, [(a["id"], a["host"])
                                                         for a in
                                                         active_agents]))
            return active_agents

        utils.wait_is_ready(
            router_id,
            is_ready=utils.resource_is(str(1),
                                       lambda x: str(len(get_actives(x)))),
            timeout=vmutils.CONF.benchmark.vm_ping_timeout,
            check_interval=vmutils.CONF.benchmark.vm_ping_poll_interval

        )
        masters = get_actives(router_id)
        LOG.info("Found router %s master on agent %s" % (router_id,
                                                         (masters[0]["id"],
                                                          masters[0]["host"])))
        return masters[0]

    def failover(self, host, command):
        """

        :param host:
        :param command:
        :return:
        """
        LOG.info("Host: %s. Injecting Failover %s" % (host["address"],
                                                      command))
        code, out, err = self._run_command(
            server_ip=host.get("address"),
            port=host.get("port", 22),
            username=host.get("username"),
            password=host.get("password"),
            key_filename=host.get("key_filename"),
            pkey=host.get("pkey"),
            command=command
        )
        if code and code > 0:
            raise exceptions.ScriptError(
                "Error running command %(command)s. "
                "Error %(code)s: %(error)s" % {
                    "command": command, "code": code, "error": err})

    def get_router(self, server, fip):
        """Retrieves server's GW router

        :param server: nova.servers obj
        :param fip: server's floating IP
        :return: uuid of server's GW router
        """

        nets = [name for name, addresses
                in server.networks.iteritems()
                if fip["ip"] in addresses]
        assert len(nets) == 1, "Found too many networks: %s" % nets
        LOG.debug("Server's network: %s" % nets[0])

        routers = [n.get("router_id") for n in
                   self.context.get("tenant", {}).get("networks", [])
                   if n["name"] == nets[0]]
        assert len(routers) == 1, "Found too many routers: %s" % routers
        LOG.debug("Server's router: %s" % routers[0])

        return routers[0]

    def _wait_for_ping(self, server_ip):
        """Ping the server repeatedly.

        Note: Shadows vm._wait_for_ping to allow dynamic names for atomic
            actions.

        :param server_ip: address of the server to ping
        :param duration: duration of the loop in seconds
        :param interval: time between iterations
        """

        server_ip = netaddr.IPAddress(server_ip)
        utils.wait_for(
            server_ip,
            is_ready=utils.resource_is(vmutils.ICMP_UP_STATUS,
                                       self._ping_ip_address),
            timeout=vmutils.CONF.benchmark.vm_ping_timeout,
            check_interval=vmutils.CONF.benchmark.vm_ping_poll_interval
        )


        # duration = duration or vmutils.CONF.benchmark.vm_ping_timeout,
        # interval = interval or vmutils.CONF.benchmark.vm_ping_poll_interval
        # server_ip = netaddr.IPAddress(server_ip)
        #
        # utils.wait_for(
        #     server_ip,
        #     is_ready=utils.resource_is(vmutils.ICMP_UP_STATUS,
        #                                self._ping_ip_address),
        #     timeout=duration,
        #     check_interval=interval
        # )

    def _run_command(self, server_ip, port, username, password, command,
                     pkey=None, key_filename=None):
        """Run command via SSH on server.

        Create SSH connection for server, wait for server to become available
        (there is a delay between server being set to ACTIVE and sshd being
        available). Then call run_command_over_ssh to actually execute the
        command.

        Note: Shadows vm.utils.VMScenario._run_command to support key_filename.

        :param server_ip: server ip address
        :param port: ssh port for SSH connection
        :param username: str. ssh username for server
        :param password: Password for SSH authentication
        :param command: Dictionary specifying command to execute.
            See `rally info find VMTasks.boot_runcommand_delete' parameter
            `command' docstring for explanation.
        :param key_filename: private key filename for SSH authentication
        :param pkey: key for SSH authentication

        :returns: tuple (exit_status, stdout, stderr)
        """
        if not key_filename:
            pkey = pkey or self.context["user"]["keypair"]["private"]
        ssh = sshutils.SSH(username, server_ip, port=port,
                           pkey=pkey, password=password,
                           key_filename=key_filename)
        self._wait_for_ssh(ssh)
        return self._run_command_over_ssh(ssh, command)
