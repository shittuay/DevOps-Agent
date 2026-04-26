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

export function registerAwsCommands(program) {
  const aws = program.command('aws').description('AWS cloud operations');

  // --- EC2 ---
  const ec2 = aws.command('ec2').description('EC2 instance operations');

  ec2.command('list')
    .description('List EC2 instances')
    .option('-r, --region <region>', 'AWS region')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora('Fetching EC2 instances...').start();
      const result = await runTool('list_ec2_instances', { region: opts.region }, spinner);
      const instances = result.instances || [];
      printTable(
        instances,
        ['instance_id', 'name', 'state', 'type', 'public_ip', 'region'],
        opts.output
      );
    });

  ec2.command('describe <instance-id>')
    .description('Describe an EC2 instance')
    .option('-r, --region <region>', 'AWS region')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (instanceId, opts) => {
      const spinner = ora(`Describing ${instanceId}...`).start();
      const result = await runTool('get_ec2_instance_details', { instance_id: instanceId, region: opts.region }, spinner);
      if (opts.output === 'json') {
        console.log(JSON.stringify(result, null, 2));
      } else {
        const inst = result.instance || result;
        printTable([inst], ['instance_id', 'name', 'state', 'type', 'public_ip', 'private_ip', 'region'], opts.output);
      }
    });

  // --- S3 ---
  const s3 = aws.command('s3').description('S3 bucket operations');

  s3.command('list')
    .description('List S3 buckets')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora('Fetching S3 buckets...').start();
      const result = await runTool('list_s3_buckets', {}, spinner);
      const buckets = result.buckets || [];
      printTable(buckets, ['name', 'creation_date', 'region'], opts.output);
    });

  // --- RDS ---
  const rds = aws.command('rds').description('RDS database operations');

  rds.command('list')
    .description('List RDS instances')
    .option('-r, --region <region>', 'AWS region')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora('Fetching RDS instances...').start();
      const result = await runTool('list_rds_instances', { region: opts.region }, spinner);
      const instances = result.instances || [];
      printTable(instances, ['db_instance_identifier', 'engine', 'status', 'endpoint', 'region'], opts.output);
    });

  // --- EKS ---
  const eks = aws.command('eks').description('EKS cluster operations');

  eks.command('list')
    .description('List EKS clusters')
    .option('-r, --region <region>', 'AWS region')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora('Fetching EKS clusters...').start();
      const result = await runTool('list_eks_clusters', { region: opts.region }, spinner);
      const clusters = result.clusters || [];
      printTable(clusters, ['name', 'status', 'kubernetes_version', 'region'], opts.output);
    });

  // --- Lambda ---
  const lambda = aws.command('lambda').description('Lambda function operations');

  lambda.command('list')
    .description('List Lambda functions')
    .option('-r, --region <region>', 'AWS region')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora('Fetching Lambda functions...').start();
      const result = await runTool('list_lambda_functions', { region: opts.region }, spinner);
      const functions = result.functions || [];
      printTable(functions, ['function_name', 'runtime', 'memory_size', 'last_modified'], opts.output);
    });
}
