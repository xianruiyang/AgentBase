class PythonWorker:
    value = 1

    def execute(self, amount):
        return amount + self.value


def python_wrapper():
    return PythonWorker().execute(1)


def python_leaf():
    return 1


def python_middle():
    return python_leaf()
