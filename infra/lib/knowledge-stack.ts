// Bedrock Knowledge Base over S3 Vectors (shared with Gavin, who owns the content).
// Settings: Titan Text Embeddings v2 (1024 dims, cosine); fixed-size chunks ~300 tokens / 20% overlap;
// data source inclusion prefix kb/ ONLY; non-filterable keys AMAZON_BEDROCK_TEXT + AMAZON_BEDROCK_METADATA (+ title, section, original).
// NOTE: check on Day 1 whether CDK has high-level constructs for S3 Vectors; otherwise use Cfn* (L1) constructs.
import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export interface KnowledgeStackProps extends cdk.StackProps { knowledgeBucket: s3.Bucket }

export class KnowledgeStack extends cdk.Stack {
  readonly knowledgeBaseId: string;

  constructor(scope: Construct, id: string, props: KnowledgeStackProps) {
    super(scope, id, props);
    // TODO: vector bucket + index (non-filterable metadata keys above)
    // TODO: KB service role with read on props.knowledgeBucket (kb/ prefix) and access to the index
    // TODO: CfnKnowledgeBase (S3 Vectors storage) + CfnDataSource (inclusionPrefixes: ['kb/'], FIXED_SIZE chunking)
    this.knowledgeBaseId = 'TODO_KB_ID';
  }
}
