class Alpha:
    def ping(self):
        return 1


class Beta:
    def ping(self):
        return 2


class Holder:
    member: Alpha

    def __init__(self):
        self.member = Alpha()

    def exercise(self, parameter: Beta):
        local: Alpha = Alpha()
        inferred = Beta()
        local.ping()
        parameter.ping()
        inferred.ping()
        self.member.ping()
        self.exercise(parameter)

        def nested(value: Alpha):
            value.ping()

        named = lambda value: value.ping()
        (lambda value: value.ping())(parameter)
        dynamic = parameter if parameter else local
        dynamic.ping()
