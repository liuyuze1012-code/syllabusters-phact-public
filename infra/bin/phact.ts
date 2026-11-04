#!/usr/bin/env node
// Wires every PHACT stack together. `npx cdk deploy --all` builds the whole system.
import * as cdk from 'aws-cdk-lib';
import { FoundationStack } from '../lib/foundation-stack';
import { AuthStack } from '../lib/auth-stack';
import { DataStack } from '../lib/data-stack';
import { KnowledgeStack } from '../lib/knowledge-stack';
import { AgentStack } from '../lib/agent-stack';
import { ApiStack } from '../lib/api-stack';
import { IntakeStack } from '../lib/intake-stack';
import { WebStack } from '../lib/web-stack';
import { OpsStack } from '../lib/ops-stack';

const app = new cdk.App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION };

const foundation = new FoundationStack(app, 'Phact-Foundation', { env });
const auth = new AuthStack(app, 'Phact-Auth', { env });
const data = new DataStack(app, 'Phact-Data', { env, key: foundation.key });
const knowledge = new KnowledgeStack(app, 'Phact-Knowledge', { env, knowledgeBucket: foundation.knowledgeBucket });
const agent = new AgentStack(app, 'Phact-Agent', { env, knowledgeBaseId: knowledge.knowledgeBaseId });
new ApiStack(app, 'Phact-Api', { env, foundation, auth, data, agentRuntimeArn: agent.runtimeArn });
new IntakeStack(app, 'Phact-Intake', { env, foundation, data, knowledgeBaseId: knowledge.knowledgeBaseId });
new WebStack(app, 'Phact-Web', { env, userPoolId: auth.userPoolId, userPoolClientId: auth.userPoolClientId });
new OpsStack(app, 'Phact-Ops', { env });
