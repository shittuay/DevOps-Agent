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

  ec2.command('start <instance-id>')
    .description('Start an EC2 instance')
    .option('-r, --region <region>', 'AWS region')
    .action(async (instanceId, opts) => {
      const spinner = ora(`Starting ${instanceId}...`).start();
      const result = await runTool('manage_ec2_instance', { instance_id: instanceId, action: 'start', region: opts.region }, spinner);
      console.log(result.message || JSON.stringify(result, null, 2));
    });

  ec2.command('stop <instance-id>')
    .description('Stop an EC2 instance')
    .option('-r, --region <region>', 'AWS region')
    .action(async (instanceId, opts) => {
      const spinner = ora(`Stopping ${instanceId}...`).start();
      const result = await runTool('manage_ec2_instance', { instance_id: instanceId, action: 'stop', region: opts.region }, spinner);
      console.log(result.message || JSON.stringify(result, null, 2));
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

  // --- IAM ---
  const iam = aws.command('iam').description('IAM user and role operations');

  iam.command('users')
    .description('List IAM users')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora('Fetching IAM users...').start();
      const result = await runTool('list_iam_users', {}, spinner);
      const users = result.users || [];
      printTable(users, ['user_name', 'user_id', 'create_date', 'password_last_used'], opts.output);
    });

  iam.command('roles')
    .description('List IAM roles')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora('Fetching IAM roles...').start();
      const result = await runTool('list_iam_roles', {}, spinner);
      const roles = result.roles || [];
      printTable(roles, ['role_name', 'role_id', 'create_date', 'description'], opts.output);
    });

  // --- CloudWatch ---
  const cw = aws.command('cloudwatch').alias('cw').description('CloudWatch alarms and metrics');

  cw.command('alarms')
    .description('List CloudWatch alarms')
    .option('-r, --region <region>', 'AWS region')
    .option('-s, --state <state>', 'Filter by state: OK, ALARM, INSUFFICIENT_DATA')
    .option('-o, --output <format>', 'Output format: table or json', 'table')
    .action(async (opts) => {
      const spinner = ora('Fetching CloudWatch alarms...').start();
      const params = {};
      if (opts.region) params.region = opts.region;
      if (opts.state) params.state_value = opts.state;
      const result = await runTool('list_cloudwatch_alarms', params, spinner);
      const alarms = result.alarms || [];
      printTable(alarms, ['alarm_name', 'state_value', 'metric_name', 'namespace', 'updated_timestamp'], opts.output);
    });
}
