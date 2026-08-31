namespace SrcqSamples;

class CSharpWorker
{
    public int Execute(int amount)
    {
        return amount + 1;
    }
}

class CSharpEntry
{
    public static int CSharpWrapper()
    {
        return new CSharpWorker().Execute(1);
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
