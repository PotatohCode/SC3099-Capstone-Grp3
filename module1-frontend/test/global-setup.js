/** Runs the whole Jest suite in a non-Singapore timezone so Singapore-time formatting is really tested. */
module.exports = async () => {
  process.env.TZ = 'America/New_York'
}
