package typedgo

type Alpha struct{}
type Beta struct{}

func (a Alpha) Ping() {}
func (b *Beta) Ping() {}
func (a *Alpha) Run()  { a.Ping() }

func consume(a *Alpha, b, c *Alpha, any interface{ Ping() }, fn func()) {
	a.Ping()
	b.Ping()
	c.Ping()
	var local Alpha
	local.Ping()
	created := &Alpha{}
	created.Ping()
	Alpha.Ping(local)
	any.Ping()
	fn()
}

func uppercaseShadow(Alpha interface{ Ping() }) {
	Alpha.Ping()
}
