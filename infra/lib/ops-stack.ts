// Budget alarm ($350 of the $500 sandbox cap), CloudTrail, and a CloudWatch dashboard (job counts, durations, failures).
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';

export class OpsStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    // TODO: budgets.CfnBudget with this.node.tryGetContext('phact:budgetUsd'), email alert at 80%
    // TODO: cloudtrail.Trail; cloudwatch.Dashboard
  }
}
