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

export function registerDockerCommands(program) {
  const docker = program
    .command('docker')
    .description('Docker container operations');

  docker.command('ps')
    .description('List containers')
    .option('-a, --all', 'Show all containers (including stopped)')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora('Fetching containers...').start();
      const result = await runTool('docker_list_containers', { all: !!opts.all }, spinner);
      const containers = result.containers || [];
      printTable(containers, ['id', 'name', 'image', 'status', 'ports', 'created'], opts.output);
    });

  docker.command('images')
    .description('List Docker images')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora('Fetching images...').start();
      const result = await runTool('docker_list_images', {}, spinner);
      const images = result.images || [];
      printTable(images, ['repository', 'tag', 'image_id', 'size', 'created'], opts.output);
    });

  docker.command('logs <container>')
    .description('Get container logs')
    .option('-l, --lines <n>', 'Number of lines (tail)', '100')
    .action(async (container, opts) => {
      const spinner = ora(`Fetching logs for ${container}...`).start();
      const result = await runTool('docker_get_container_logs', {
        container_id: container,
        tail: parseInt(opts.lines, 10),
      }, spinner);
      console.log(result.logs || result.output || '(no logs)');
    });

  docker.command('stats')
    .description('Show container resource usage')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora('Fetching stats...').start();
      const result = await runTool('docker_get_stats', {}, spinner);
      const stats = result.stats || [];
      printTable(stats, ['name', 'cpu_percent', 'mem_usage', 'mem_percent', 'net_io', 'block_io'], opts.output);
    });
}
