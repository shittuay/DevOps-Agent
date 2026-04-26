import ora from 'ora';
import { executeTool } from '../lib/api-client.js';
import { error, dim } from '../lib/output.js';

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

export function registerTerraformCommands(program) {
  const tf = program
    .command('terraform')
    .alias('tf')
    .description('Terraform workspace operations');

  tf.command('plan')
    .description('Run terraform plan')
    .option('-d, --dir <path>', 'Working directory', '.')
    .option('--var-file <file>', 'Terraform var file')
    .action(async (opts) => {
      const spinner = ora('Running terraform plan...').start();
      const params = { working_dir: opts.dir };
      if (opts.varFile) params.var_file = opts.varFile;
      const result = await runTool('terraform_plan', params, spinner);
      console.log(result.output || result.plan_output || JSON.stringify(result, null, 2));
      if (result.exit_code !== undefined) {
        dim(`Exit code: ${result.exit_code}`);
      }
    });

  tf.command('apply')
    .description('Run terraform apply')
    .option('-d, --dir <path>', 'Working directory', '.')
    .option('--auto-approve', 'Skip interactive approval')
    .option('--var-file <file>', 'Terraform var file')
    .action(async (opts) => {
      const params = { working_dir: opts.dir, auto_approve: !!opts.autoApprove };
      if (opts.varFile) params.var_file = opts.varFile;
      const spinner = ora('Running terraform apply...').start();
      const result = await runTool('terraform_apply', params, spinner);
      console.log(result.output || result.apply_output || JSON.stringify(result, null, 2));
    });

  tf.command('output')
    .description('Show terraform outputs')
    .option('-d, --dir <path>', 'Working directory', '.')
    .option('--json', 'Output as JSON')
    .action(async (opts) => {
      const spinner = ora('Fetching terraform outputs...').start();
      const result = await runTool('terraform_output', { working_dir: opts.dir }, spinner);
      if (opts.json) {
        console.log(JSON.stringify(result.outputs || result, null, 2));
      } else {
        const outputs = result.outputs || result;
        if (typeof outputs === 'object') {
          for (const [key, val] of Object.entries(outputs)) {
            const value = typeof val === 'object' ? JSON.stringify(val.value ?? val) : String(val);
            console.log(`${key} = ${value}`);
          }
        } else {
          console.log(outputs);
        }
      }
    });

  tf.command('workspaces')
    .description('List terraform workspaces')
    .option('-d, --dir <path>', 'Working directory', '.')
    .action(async (opts) => {
      const spinner = ora('Listing workspaces...').start();
      const result = await runTool('terraform_workspace_list', { working_dir: opts.dir }, spinner);
      const workspaces = result.workspaces || [];
      workspaces.forEach(w => console.log(w));
    });

  tf.command('validate')
    .description('Validate terraform configuration')
    .option('-d, --dir <path>', 'Working directory', '.')
    .action(async (opts) => {
      const spinner = ora('Validating configuration...').start();
      const result = await runTool('terraform_validate', { working_dir: opts.dir }, spinner);
      console.log(result.output || JSON.stringify(result, null, 2));
    });
}
