// API Gateway (REST) + Cognito authorizer → API Lambda (FastAPI/Mangum); worker Lambda (async jobs).
// Both Lambdas: Python 3.12. Worker timeout 10 min. Env: TABLE_NAME, buckets, WORKER_FUNCTION, AGENT_MODE, AGENT_RUNTIME_ARN, GUARDRAIL_ID.
// Also the Bedrock Guardrail (denied topics, content + prompt-attack filters).
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { FoundationStack } from './foundation-stack';
import { AuthStack } from './auth-stack';
import { DataStack } from './data-stack';

export interface ApiStackProps extends cdk.StackProps {
  foundation: FoundationStack; auth: AuthStack; data: DataStack; agentRuntimeArn: string;
}

export class ApiStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);
    // TODO: apiFn  = Lambda (backend/, handler app.main.handler)
    // TODO: workerFn = Lambda (backend/, handler app.worker.handler, timeout 10 min); apiFn may invoke it
    // TODO: grants: table read/write; uploads read/write; exports write; knowledge read (citation links);
    //       comprehend:DetectPiiEntities; bedrock:ApplyGuardrail; bedrock-agentcore:InvokeAgentRuntime (worker only)
    // TODO: RestApi + CognitoUserPoolsAuthorizer on /api/*; /health public
    // TODO: CfnGuardrail
  }
}
