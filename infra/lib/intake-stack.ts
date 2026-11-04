// Source intake pipeline (tier 3): EventBridge on intake/incoming/ → Step Functions: extract → clean → check →
// ONE human gate (.waitForTaskToken: the ASPPH reviewer approves & publishes in the Review console) →
// publish to knowledge kb/ → StartIngestionJob → smoke test → status back to the console.
// No IT role: the reviewer never touches AWS directly; the pipeline's own IAM role does the publishing.
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { FoundationStack } from './foundation-stack';
import { DataStack } from './data-stack';

export interface IntakeStackProps extends cdk.StackProps {
  foundation: FoundationStack; data: DataStack; knowledgeBaseId: string;
}

export class IntakeStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: IntakeStackProps) {
    super(scope, id, props);
    // TODO: Lambdas: extract, clean, check, publish, smoke_test (same logic as scripts/add_source.py)
    // TODO: StateMachine with one .waitForTaskToken gate (reviewer approve & publish); store the token on SOURCE#<id>
    // TODO: pipeline role: write knowledge kb/ + originals/, bedrock:StartIngestionJob/GetIngestionJob, bedrock:Retrieve
    // TODO: retire flow: delete from kb/ + originals/, re-sync (triggered by POST /api/review/{id}/retire)
  }
}
