class Widget
{
public:
    int Value = 1;
};

enum class Mode
{
    First,
    Second,
};

using Count = int;

int DeclaredOnly(int ValueOnly);

int GlobalValue = 2;

int BuildTool(int Input)
{
    return Input + GlobalValue;
}

int CanBuildTool()
{
    return BuildTool(1);
}

void UpdateGlobalValue()
{
    GlobalValue = 3;
}

int Wrapper()
{
    return CanBuildTool();
}

int Recursive()
{
    return Recursive();
}

namespace Other
{
int BuildTool(int Input)
{
    return Input;
}
}

int CallOtherBuildTool()
{
    return Other::BuildTool(2);
}

#include "declarations.h"

int VirtualWorker::RunVirtual()
{
    return 1;
}

namespace Alpha::Beta::Gamma
{
int NestedLeaf()
{
    return 1;
}

int NestedMiddle()
{
    return NestedLeaf();
}
}

int NestedTop()
{
    return Alpha::Beta::Gamma::NestedMiddle();
}

struct FixtureWorker
{
    int Tick();
};

int FixtureWorker::Tick()
{
    return 1;
}

int UseFixtureWorker()
{
    FixtureWorker Worker;
    return Worker.Tick();
}

Widget DirectWidget(Widget{});
