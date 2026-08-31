namespace SrcqSamples;

partial class CSharpEntry
{
    public int CSharpPropertyChain()
    {
        return _services.Worker.Execute(5);
    }

    public int CSharpStaticCall()
    {
        return CSharpStaticWorker.Execute(6);
    }
}

static class CSharpStaticWorker
{
    public static int Execute(int amount)
    {
        return amount * 2;
    }
}
