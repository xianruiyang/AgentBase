using System;

namespace SrcqLexicalScopes;

class CSharpLexicalWorker
{
    public int Execute(int amount) => amount + 1;
}

class CSharpLexicalAlternateWorker
{
    public int Execute(int amount) => amount - 1;
}

class CSharpScopeEntry
{
    public int CSharpSiblingScopes()
    {
        var total = 0;
        {
            CSharpLexicalWorker scoped = new();
            total += scoped.Execute(1);
        }
        {
            CSharpLexicalAlternateWorker scoped = new();
            total += scoped.Execute(2);
        }
        return total;
    }

    public int CSharpLambdaScope(CSharpLexicalWorker worker)
    {
        Func<CSharpLexicalAlternateWorker, int> callback =
            (CSharpLexicalAlternateWorker worker) => worker.Execute(1);
        return worker.Execute(2) + callback(new CSharpLexicalAlternateWorker());
    }

    public int CSharpExitedScope()
    {
        {
            CSharpLexicalWorker scoped = new();
        }
        return scoped.Execute(1);
    }
}
