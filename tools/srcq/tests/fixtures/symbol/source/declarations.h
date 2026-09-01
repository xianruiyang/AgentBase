class VirtualWorker
{
public:
    virtual int RunVirtual();
};

class InlineWorker
{
public:
    int RunInline()
    {
        return 7;
    }

    int CallInline()
    {
        return RunInline();
    }

    int DeclaredInline();
};

class InlineWorkerHolder
{
public:
    InlineWorker* InlineMember;
    int CallMember() { return InlineMember->RunInline(); }
};

class InlineWorkerChain
{
public:
    InlineWorkerHolder* Holder;
    int CallChain() { return Holder->InlineMember->RunInline(); }
};

class InlineWorkerSharedHolder
{
public:
    std::shared_ptr<InlineWorker> InlineShared;
    int CallShared() { return InlineShared->RunInline(); }
};

class InlineWorkerLateHolder
{
public:
    int CallLate() { return InlineLate->RunInline(); }
    InlineWorker* InlineLate;
};

class FriendHolder
{
public:
    friend int FriendFree() { return 11; }
};

class CommentFriendHolder
{
public:
    // friend is only a comment here.
    int OrdinaryInline() { return 12; }
};

class DeclaratorProbe
{
};

class DeclaratorNoise
{
public:
    DeclaratorProbe* Value;
    const DeclaratorProbe Value2;
    DeclaratorProbe Make();
    int Defaulted(int Value = DeclaratorProbe());
};
