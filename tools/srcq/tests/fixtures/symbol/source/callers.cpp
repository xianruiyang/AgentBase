int CrossFileTarget();

int FirstCrossFileCaller()
{
    return CrossFileTarget();
}

int SecondCrossFileCaller()
{
    return CrossFileTarget();
}

namespace OtherIncoming
{
int RepeatedIncomingOwner()
{
    return 0;
}
}
