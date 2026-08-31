class Alpha { run() {} }
class Beta { run() {} }

class Harness {
  field = new Alpha();
  constructor() { this.other = new Beta(); }
  execute() {
    const local = new Alpha();
    local.run();
    this.field.run();
    this.other.run();
    new Beta().run();
    Alpha.run();
    this["field"].run();
    local["run"]();
  }
}

const arrowOwner = () => { const local = new Beta(); local.run(); };
const expressionOwner = function () { new Alpha().run(); };
Alpha.prototype.patched = function () {};
const functionValue = Alpha.prototype.patched;
functionValue();
