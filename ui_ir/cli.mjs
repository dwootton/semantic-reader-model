#!/usr/bin/env node
/** Local stdin/stdout bridge. Does not execute capture content or make model calls. */
import { adaptDOM } from './dom/adapter.mjs';
import { compactIR, expandIR } from './compact.mjs';
import { modelPacket, validateModelReferences } from './codec.mjs';
import { navigationPacket, validateNavigationReferences } from './navigation.mjs';
import { validateObservation, validateView, observationHash, stableStringify } from './validate.mjs';

const MAX_BYTES = 32 * 1024 * 1024;
let length = 0;
const chunks = [];
try {
  for await (const chunk of process.stdin) {
    length += chunk.length;
    if (length > MAX_BYTES) throw new Error('Input byte limit exceeded');
    chunks.push(chunk);
  }
  const command = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  let output;
  const packageResult = (bundle, result) => ({
    ...(bundle ? { bundle } : {}), result, packet: modelPacket(result.view),
    regionPackets: (result.partition?.regions || []).map(region => ({ result: region, packet: modelPacket(region.view) })),
  });
  switch (command.operation) {
    case 'adapt': output = adaptDOM(command.input, command.policy); break;
    case 'pipeline': {
      const bundle = adaptDOM(command.input, command.policy);
      output = packageResult(bundle, compactIR(bundle.observation, command.request)); break;
    }
    case 'compact': output = packageResult(null, compactIR(command.observation, command.request)); break;
    case 'expand': output = packageResult(null, expandIR(command.observation, command.priorResult, command.gapIds, command.request)); break;
    case 'validate': validateObservation(command.observation); output = { valid: true, observationHash: observationHash(command.observation) }; break;
    case 'navigation': {
      validateObservation(command.observation); validateView(command.view);
      if (command.view.observationHash !== observationHash(command.observation)
          || command.view.snapshotId !== command.observation.snapshotId) throw new Error('Stale model view');
      output = navigationPacket(command.view, command.observation); break;
    }
    case 'navigation-references':
    case 'references': {
      let expected = command.expected || {};
      if (command.view || command.observation) {
        validateObservation(command.observation); validateView(command.view);
        const hash = observationHash(command.observation);
        if (command.view.observationHash !== hash || command.view.snapshotId !== command.observation.snapshotId) throw new Error('Stale model view');
        expected = { snapshotId: command.observation.snapshotId, observationHash: hash, viewHash: observationHash(command.view) };
        if (command.operation === 'navigation-references') expected.packetHash = navigationPacket(command.view, command.observation).packetHash;
      }
      const validator = command.operation === 'navigation-references' ? validateNavigationReferences : validateModelReferences;
      output = { ids: validator(command.packet, command.refs, expected) }; break;
    }
    default: throw new Error('Unknown IR operation');
  }
  process.stdout.write(stableStringify(output) + '\n');
} catch (error) {
  // Error messages never print the entire input or native source payload.
  process.stderr.write(JSON.stringify({ error: error.name || 'Error', code: error.code || 'ir_failed', message: error.message }) + '\n');
  process.exitCode = 1;
}
