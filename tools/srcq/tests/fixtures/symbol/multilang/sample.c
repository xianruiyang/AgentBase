int c_execute(int amount) {
    return amount + 1;
}

int c_wrapper(void) {
    return c_execute(1);
}

int c_leaf(void) {
    return 1;
}

int c_middle(void) {
    return c_leaf();
}
