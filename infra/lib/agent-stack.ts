// The AgentCore runtime that runs agent/main.py, and its IAM role
// (Bedrock InvokeModel on the two inference profiles + bedrock:Retrieve on the KB).
// If CDK support is missing, deploy with the AgentCore CLI and pass the ARN in via context.
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface AgentStackProps extends cdk.StackProps { knowledgeBaseId: string }

export class AgentStack extends cdk.Stack {
  readonly runtimeArn: string;

  constructor(scope: Construct, id: string, props: AgentStackProps) {
    super(scope, id, props);
    // TODO: runtime with env KB_ID, MODEL_STRONG, MODEL_FAST (set at launch, not configure)
    this.runtimeArn = this.node.tryGetContext('phact:agentRuntimeArn') ?? 'TODO_AGENT_RUNTIME_ARN';
  }
}
