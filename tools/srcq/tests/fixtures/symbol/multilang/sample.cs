namespace SrcqSamples;

class CSharpWorker
{
    public int Execute(int amount)
    {
        return amount + 1;
    }
}

class CSharpAlternateWorker
{
    public int Execute(int amount)
    {
        return amount - 1;
    }
}

partial class CSharpEntry
{
    private readonly CSharpWorker _worker = new();
    private readonly CSharpAlternateWorker _alternate = new();

    public static int CSharpWrapper()
    {
        return new CSharpWorker().Execute(1);
    }

    public int CSharpTypedReceivers(CSharpWorker worker)
    {
        var local = new CSharpWorker();
        return worker.Execute(1)
            + _worker.Execute(2)
            + local.Execute(3)
            + _alternate.Execute(4);
    }

    public int CSharpUnknownReceiver(dynamic worker)
    {
        return worker.Execute(1);
    }

    private static int CSharpLeaf()
    {
        return 1;
    }

    public static int CSharpMiddle()
    {
        return CSharpLeaf();
    }
}
