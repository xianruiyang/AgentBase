const supportedArchitectures = new Set(['x64', 'arm64']);

if (process.platform === 'win32' && !supportedArchitectures.has(process.arch)) {
  throw new Error(`Unsupported Windows architecture: ${process.arch}`);
}

process.stdout.write('Native compilation is deferred to the explicit build:native scripts.\n');

