function get() {
    return process.env.ADMIN_TOKEN || "";
}

export default { get };
