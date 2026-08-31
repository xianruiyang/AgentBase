namespace SrcqSamples;

partial class CSharpEntry
{
    private readonly CSharpServices _services = new();
}

class CSharpServices
{
    public CSharpWorker Worker { get; } = new();
}
