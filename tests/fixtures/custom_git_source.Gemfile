git_source(:github) { |repo_name| "https://github.com/#{repo_name}.git" }
git_source(:gitlab) do |repo|
  repo = "#{repo}/#{repo}" unless repo.include?("/")
  "https://gitlab.com/#{repo}.git"
end
git_source(:ssh) { |repo| "git@example.com:#{repo}.git" }
gem 'a', github: 'acme/a'
gem 'b', github: 'solo'
gem 'c', gitlab: 'acme/c'
gem 'd', gitlab: 'solo', branch: 'dev'
gem 'e', ssh: 'team/e'
