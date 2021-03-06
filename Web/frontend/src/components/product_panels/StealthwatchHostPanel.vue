<template>
  <div class="host-panel">
    <div class="row">
      <div class="col">
        <div class="host-panel-header">
          <i v-show="flowsLoading" id="loading" class="fa fa-refresh fa-spin fa-1x"></i>
          Stealthwatch
        </div>
      </div>
    </div>
    <div class="row">
      <div class="col">
        <div class="host-panel-content">
          <span v-if="flows.length > 0 || flowsLoading">
            <VisNetwork
              id="network-view"
              ref="network"
              :edges="edges"
              :nodes="nodes"
              :options="options"
              :events="['stabilized']"
              @stabilized="onGraphStabilized"
              style="height: 60vh"
            ></VisNetwork>
          </span>
          <div v-else class="text-center">No Flow Data</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import axios from 'axios';
import { Network } from 'vue2vis';

export default {
  components: {
    VisNetwork: Network,
  },
  props: ['hostIp'],
  data() {
    return {
      edges: [],
      flows: [],
      flowsLoading: false,
      hostSnapshot: null,
      nodes: [],
      network: null,
      options: {
        nodes: {
          shape: 'dot',
        },
        edges: {
          scaling: {
            label: {
              enabled: false,
            },
          },
        },
        physics: {
          barnesHut: {
            gravitationalConstant: -7000,
            damping: 0.25,
          },
        },
        groups: {
          0: {
            color: {
              border: '#41A906',
              background: '#7BE141',
              highlight: {
                border: '#41A906',
                background: '#A1EC76',
              },
              hover: {
                border: '#41A906',
                background: '#A1EC76',
              },
            },
          },
          1: {
            color: {
              border: '#2B7CE9',
              background: '#97C2FC',
              highlight: {
                border: '#2B7CE9',
                background: '#D2E5FF',
              },
              hover: {
                border: '#2B7CE9',
                background: '#D2E5FF',
              },
            },
          },
          2: {
            color: {
              border: '#FFA500',
              background: '#FFFF00',
              highlight: {
                border: '#FFA500',
                background: '#FFFFA3',
              },
              hover: {
                border: '#FFA500',
                background: '#FFFFA3',
              },
            },
          },
          3: {
            color: {
              border: '#FA0A10',
              background: '#FB7E81',
              highlight: {
                border: '#FA0A10',
                background: '#FFAFB1',
              },
              hover: {
                border: '#FA0A10',
                background: '#FFAFB1',
              },
            },
          },
        },
      },
    };
  },
  computed: {
    timeframe() {
      // Limit Stealthwatch Flow Queries to 24 hours
      if (this.$store.state.timeframe > 24) return 24;

      return this.$store.state.timeframe;
    },
  },
  methods: {
    getFlows() {
      this.flowsLoading = true;
      const path = `http://${window.location.hostname}:5000/api/stealthwatch/flows?host_ip=${this.hostIp}&timeframe=${this.timeframe}`;
      axios
        .get(path)
        .then((res) => {
          console.log(res);
          this.flowsLoading = false;
          if (res.status === 204) return;
          this.flows = res.data.getFlowsResponse['flow-list'].flow;
        })
        .catch((error) => {
          // eslint-disable-next-line
          this.flowsLoading = false;
          console.error(error);
          this.$store.dispatch('addError', { message: error });
        });
    },
    getHostSnapshot() {
      const path = `http://${window.location.hostname}:5000/api/stealthwatch/host-snapshot?host_ip=${this.hostIp}`;
      axios
        .get(path)
        .then((res) => {
          console.log(res);
          this.hostSnapshot = res.data.getHostSnapshotResponse['host-snapshot'];
        })
        .catch((error) => {
          // eslint-disable-next-line
          console.error(error);
          this.$store.dispatch('addError', { message: error });
        });
    },
    processFlows() {
      // Placeholders for edges and nodes
      this.edges = [];
      this.nodes = [];

      // Rip through each flow and add our edges and nodes
      this.flows.forEach((flow) => {
        this.processNode(flow.server);
        this.processNode(flow.client);

        this.processEdge(flow);
      });
    },
    processNode(node) {
      // Get the node ID / IP
      let hostId = node['@ip-address'];
      const hostIp = node['@ip-address'];

      // Get the host Country
      const hostCountry = node['@country'];

      // Get the byte count
      const hostValue = node['@bytes'];

      // Placeholders
      let hostGroup;
      let hostLabel;

      // Check to see if it's an inside host, then group by country
      if (['XR', 'XU', 'XL'].includes(hostCountry)) {
        hostLabel = hostIp;
        if (hostIp === this.hostIp) hostGroup = 0;
        else hostGroup = 1;
      } else {
        hostId = hostCountry;
        hostLabel = hostCountry;
        hostGroup = 2;
      }

      let nodeExists = false;

      this.nodes.forEach((currentNode) => {
        if (currentNode.id === hostId) {
          nodeExists = true;
          currentNode = {
            id: hostId,
            label: hostLabel,
            group: hostGroup,
            value: currentNode.value + hostValue,
          };
        }
      });

      if (!nodeExists) {
        this.nodes.push({
          id: hostId,
          label: hostLabel,
          group: hostGroup,
          value: hostValue,
        });
      }

      return hostId;
    },
    processEdge(edge) {
      let clientId = edge.client['@country'];
      let serverId = edge.server['@country'];

      // Calculate a Client ID
      if (['XR', 'XU', 'XL'].includes(clientId)) {
        clientId = edge.client['@ip-address'];
      }

      // Calculate a Server ID
      if (['XR', 'XU', 'XL'].includes(serverId)) {
        serverId = edge.server['@ip-address'];
      }

      // Get the total bytes for the flow
      const totalBytes = edge['@total-bytes'];

      let edgeExists = false;
      const unidirectional = (edge.client['@bytes'] === '0') || (edge.server['@bytes'] === '0');

      // Check to see if we need to update an edge
      this.edges.forEach((currentEdge) => {
        if (currentEdge.id === clientId + serverId) {
          edgeExists = true;
          currentEdge = {
            dashes: !currentEdge.dashes || !unidirectional,
            value: currentEdge.value + totalBytes,
          };
        }
      });

      if (!edgeExists) {
        this.edges.push({
          id: clientId + serverId,
          from: clientId,
          to: serverId,
          dashes: unidirectional,
          arrows: 'to',
          value: totalBytes,
        });
      }
    },
    onGraphStabilized() {
      this.$refs.network.fit({ animation: true });
    },
  },
  watch: {
    flows(newVal, oldVal) {
      if (oldVal.length === 0) {
        this.$refs.network.moveTo({ scale: 0.2 });
      }
      this.processFlows();
    },
    hostIp() {
      this.getFlows();
    },
    timeframe() {
      this.getFlows();
    },
  },
  created() {
    this.getFlows();
    // this.getHostSnapshot();
  },
};
</script>

<style lang="scss" scoped>
#loading {
  float: right;
  padding: 5px;
}

.host-panel-content {
  overflow: hidden;
}
</style>
