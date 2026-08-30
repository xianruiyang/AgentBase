package sample

type GoWorker struct {
	Value int
}

func (worker GoWorker) Execute(amount int) int {
	return amount + worker.Value
}

func goWrapper() int {
	return GoWorker{Value: 1}.Execute(1)
}
