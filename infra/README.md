# Infrastructure: AWS CDK (TypeScript)

**Owner: software engineering track.** Every AWS resource as code (required by the hackathon). `npx cdk deploy --all` builds the whole system.

```bash
cd infra
npm install
npx cdk bootstrap          # once per account/region
npx cdk synth              # check it compiles
npx cdk deploy --all
```

## Files

| File | What it does | Status |
|---|---|---|
| `package.json` | CDK dependencies and npm scripts | ready |
| `cdk.json` | How CDK runs the app; context: stage, budget | ready |
| `tsconfig.json` | TypeScript settings | ready |
| `bin/phact.ts` | Creates every stack and wires them together | ready |
| `lib/foundation-stack.ts` | KMS key + 4 buckets (knowledge, uploads, exports, intake): encrypted, private, HTTPS only | ready, CORS TODO |
| `lib/auth-stack.ts` | Cognito pool, no sign-up, `custom:school_id`, groups faculty / school-admin / aspph-reviewer | ready |
| `lib/data-stack.ts` | The DynamoDB table + GSI1, TTL, PITR | ready |
| `lib/knowledge-stack.ts` | Bedrock KB over S3 Vectors, synced from `kb/` only, fixed-size chunks | TODO (shared with Gavin) |
| `lib/agent-stack.ts` | AgentCore runtime + its IAM role | TODO |
| `lib/api-stack.ts` | API Gateway + Cognito authorizer, API Lambda, worker Lambda, Guardrail | TODO |
| `lib/intake-stack.ts` | Step Functions with one reviewer gate (approve & publish), publish + sync + smoke test, retire | TODO (stretch) |
| `lib/web-stack.ts` | Amplify Hosting for `frontend/` | TODO |
| `lib/ops-stack.ts` | Budget alarm at $350, CloudTrail, dashboard | TODO |

## Order to build
Foundation → Auth → Data → Api (with `AGENT_MODE=mock`) → Web. **That's a working, testable product with no AI.** Then Knowledge → Agent, and switch `AGENT_MODE` to `agentcore`. Intake and Ops come last.

## Watch out
- Lambdas run **Python 3.12** (Lambda doesn't support 3.14).
- S3 Vectors and AgentCore are new services. If CDK lacks high-level constructs, use `Cfn*` (L1) constructs, or deploy the agent with the AgentCore CLI and pass its ARN as context `phact:agentRuntimeArn`.
- `removalPolicy: DESTROY` is set for the sandbox. Change it before any real use.
