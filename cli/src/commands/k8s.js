import ora from 'ora';
import { executeTool } from '../lib/api-client.js';
import { error, printTable } from '../lib/output.js';

async function runTool(toolName, params, spinner) {
  try {
    const data = await executeTool(toolName, params);
    spinner.stop();
    return data.result;
  } catch (err) {
    spinner.fail(err.message);
    process.exit(1);
  }
}

export function registerK8sCommands(program) {
  const k8s = program
    .command('k8s')
    .description('Kubernetes cluster operations');

  k8s.command('pods')
    .description('List pods')
    .option('-n, --namespace <ns>', 'Namespace', 'default')
    .option('-c, --context <ctx>', 'Kubeconfig context')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora(`Fetching pods in ${opts.namespace}...`).start();
      const params = { namespace: opts.namespace };
      if (opts.context) params.context = opts.context;
      const result = await runTool('get_pods', params, spinner);
      const pods = result.pods || [];
      printTable(pods, ['name', 'status', 'ready', 'restarts', 'age', 'node'], opts.output);
    });

  k8s.command('deployments')
    .description('List deployments')
    .option('-n, --namespace <ns>', 'Namespace', 'default')
    .option('-c, --context <ctx>', 'Kubeconfig context')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora(`Fetching deployments in ${opts.namespace}...`).start();
      const params = { namespace: opts.namespace };
      if (opts.context) params.context = opts.context;
      const result = await runTool('get_deployments', params, spinner);
      const deployments = result.deployments || [];
      printTable(deployments, ['name', 'ready', 'available', 'age'], opts.output);
    });

  k8s.command('services')
    .description('List services')
    .option('-n, --namespace <ns>', 'Namespace', 'default')
    .option('-c, --context <ctx>', 'Kubeconfig context')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora(`Fetching services in ${opts.namespace}...`).start();
      const params = { namespace: opts.namespace };
      if (opts.context) params.context = opts.context;
      const result = await runTool('get_services', params, spinner);
      const services = result.services || [];
      printTable(services, ['name', 'type', 'cluster_ip', 'external_ip', 'ports', 'age'], opts.output);
    });

  k8s.command('nodes')
    .description('List cluster nodes')
    .option('-c, --context <ctx>', 'Kubeconfig context')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora('Fetching nodes...').start();
      const params = {};
      if (opts.context) params.context = opts.context;
      const result = await runTool('get_nodes', params, spinner);
      const nodes = result.nodes || [];
      printTable(nodes, ['name', 'status', 'roles', 'age', 'version'], opts.output);
    });

  k8s.command('logs <pod>')
    .description('Get pod logs')
    .option('-n, --namespace <ns>', 'Namespace', 'default')
    .option('-c, --container <container>', 'Container name')
    .option('-l, --lines <n>', 'Number of lines', '100')
    .option('--context <ctx>', 'Kubeconfig context')
    .action(async (pod, opts) => {
      const spinner = ora(`Fetching logs for ${pod}...`).start();
      const params = {
        pod_name: pod,
        namespace: opts.namespace,
        tail_lines: parseInt(opts.lines, 10),
      };
      if (opts.container) params.container = opts.container;
      if (opts.context) params.context = opts.context;
      const result = await runTool('get_pod_logs', params, spinner);
      console.log(result.logs || result.output || '(no logs)');
    });
}
